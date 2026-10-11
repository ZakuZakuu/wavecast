"""Checking the host's factual sentences against the sources the application actually holds.

The Writer is told to use only the scoped evidence, but nothing used to check that it did: a
sentence such as "the song was composed by X" could rest on a model's memory (or on a name
that merely appears near the subject in a web page) and still be spoken.  This module checks
each factual sentence before it is voiced:

* Code decides what must be supported: attribution and creation words (who composed, wrote,
  sang, directed, released), years, and the names of works in 《》.  A sentence the checker
  calls "not factual" is still checked when it carries one of those markers.
* One short model call returns, per factual sentence, "supported", "contradicted" or
  "insufficient" together with the source it relies on and a quote.  The quote must be found
  in that source (code checks), so the checker cannot supply evidence from its own memory.
  The sources are the scoped evidence plus the catalog's own lines about the tracks.
* A name in 《》 must be a track of this programme or appear in the evidence; a title the
  Writer made up is not.

Subjective listening, transitions and "this plays next" are not facts and need no source.
The checker degrades: if its call fails, the code-only checks still apply and the programme
carries on.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from wavecast.narration_quality import years_in
from wavecast.providers.errors import ProviderInvalidResponseError
from wavecast.providers.profiles import InferenceProfile, StructuredTransport
from wavecast.spoken_form import KnownTrack, to_spoken_form
from wavecast.text_identity import canonical_name

from .fast_start import FastStructuredProvider
from .models import ClaimSupport, ClaimType, Evidence, RadioScript, RadioScriptBlockKind

logger = logging.getLogger(__name__)

CATALOG_SOURCE = "catalog"
_SENTENCE = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]*|\n+")
_TITLE_IN_BRACKETS = re.compile(r"《([^》]{1,40})》")
_GENERIC_TITLES = frozenset({"这首歌", "这首曲子", "这支曲子", "这首", "这支曲子"})
_IGNORED = re.compile(r"[\s，。！？、；：,.!?;:“”\"'‘’《》「」『』（）()\-—…·]+")
_MIN_QUOTE_CHARS = 4
_QUOTE_CONTAINMENT = 0.8

# Who did what.  Each family's words are interchangeable evidence for each other; a sentence
# that makes a claim of one family is supported only by a quote that speaks of that family.
_ROLE_FAMILIES: dict[str, tuple[str, ...]] = {
    "composition": ("作曲", "谱曲", "编曲", "配乐", "创作", "写成", "写了", "音乐"),
    "lyrics": ("作词", "填词", "词作"),
    "performance": ("演唱", "主唱", "领唱", "唱的", "唱了", "献唱", "歌手", "演奏", "录制"),
    "film": ("导演", "执导", "主演", "拍摄", "电影", "影片", "动画"),
    "release": ("发行", "首映", "上映", "公映", "出版", "专辑", "原声带", "票房", "收录"),
    "award": ("获奖", "荣获", "入围", "奖"),
}
_ROLE_TRIGGER = re.compile(
    "|".join(
        re.escape(word)
        for words in _ROLE_FAMILIES.values()
        for word in words
        if word not in ("音乐", "电影", "影片", "动画", "奖", "歌手", "录制")
    )
    + r"|唱的是|出自|寄给|写给|参与|制作|改编|根据|诞生|灵感"
)


class FactFinding(BaseModel):
    """The checker's verdict on one sentence.

    The schema is deliberately forgiving about free text (long quotes are cut, an unknown
    verdict means "not a fact") so that a slightly off answer does not discard the check.
    """

    sentence: int = Field(ge=0)
    verdict: Literal["supported", "contradicted", "insufficient", "not_factual"]
    source: str = Field(default="")
    quote: str = Field(default="")

    @field_validator("source", "quote", mode="before")
    @classmethod
    def _clip(cls, value: object) -> str:
        return str(value or "")[:300]


class FactCheck(BaseModel):
    findings: list[FactFinding] = Field(default_factory=list, max_length=80)


@dataclass(frozen=True)
class SentenceIssue:
    block: int
    sentence: int  # index within the block
    text: str
    code: str
    message: str


@dataclass
class FactReport:
    issues: list[SentenceIssue] = field(default_factory=list)
    # Per block: the factual sentences that were found in a source, with that source's id.
    supported: dict[int, list[ClaimSupport]] = field(default_factory=dict)
    model_checked: bool = False


def split_sentences(text: str) -> list[str]:
    return [part for part in _SENTENCE.findall(text) if part.strip()]


def _squash(text: str) -> str:
    return _IGNORED.sub("", canonical_name(text))


def _bigrams(text: str) -> set[str]:
    squashed = _squash(text)
    return {squashed[i : i + 2] for i in range(len(squashed) - 1)}


def quote_in_source(quote: str, source: str) -> bool:
    """True when the quote is (nearly) a verbatim stretch of the source.

    Script variants, spacing and punctuation are ignored, so a quote that the checker copied
    from a Traditional-Chinese page still matches; text that is not there does not.
    """

    squashed = _squash(quote)
    if len(squashed) < _MIN_QUOTE_CHARS:
        return False
    if squashed in _squash(source):
        return True
    wanted = _bigrams(quote)
    return bool(wanted) and len(wanted & _bigrams(source)) / len(wanted) >= _QUOTE_CONTAINMENT


def role_families(text: str) -> set[str]:
    return {
        family
        for family, words in _ROLE_FAMILIES.items()
        if any(word in text for word in words if word not in ("音乐", "电影", "影片", "动画", "奖", "歌手"))
    }


def must_be_supported(sentence: str) -> bool:
    """Attributions, creation stories and dated statements are never taken on trust."""

    return bool(_ROLE_TRIGGER.search(sentence)) or bool(years_in(sentence))


def _known_titles(tracks: Sequence[KnownTrack], route_labels: Sequence[str]) -> set[str]:
    titles = {_squash(title) for title in _GENERIC_TITLES}
    for track in tracks:
        titles.add(_squash(track.title))
        if track.spoken_title:
            titles.add(_squash(track.spoken_title))
    for label in route_labels:
        titles.add(_squash(label.split(" - ", 1)[-1]))
    return {title for title in titles if title}


def unknown_titles(
    sentence: str, known: set[str], corpus: str
) -> list[str]:
    """Names in 《》 that are neither a track of this programme nor found in the evidence."""

    found: list[str] = []
    haystack = _squash(corpus)
    for name in _TITLE_IN_BRACKETS.findall(sentence):
        key = _squash(name)
        if not key or key in known:
            continue
        if any(key in title or title in key for title in known if len(title) >= 3 and len(key) >= 3):
            continue
        if key in haystack:
            continue
        found.append(name)
    return found


def _quote_names_title_variant(quote: str, sentence: str, tracks: Sequence[KnownTrack]) -> bool:
    """The quote names the original title of a track whose Chinese title the sentence uses."""

    for track in tracks:
        names = [track.title, *([track.spoken_title] if track.spoken_title else [])]
        if any(_squash(name) and _squash(name) in _squash(sentence) for name in names):
            if any(_squash(name) in _squash(quote) for name in names):
                return True
    return False


def _catalog_lines(tracks: Sequence[KnownTrack], route_labels: Sequence[str]) -> list[str]:
    lines: dict[str, str] = {}
    for track in tracks:
        zh = f"; the catalog's Chinese title: {track.spoken_title}" if track.spoken_title else ""
        lines[f"{track.artist} - {track.title}"] = (
            f"Track “{track.title}” is credited to the performer {track.artist}{zh}."
        )
    for label in route_labels:
        artist, _sep, title = label.partition(" - ")
        if title and label not in lines:
            lines[label] = f"Track “{title}” is credited to the performer {artist}."
    return list(lines.values())


_PROMPT = """You check what a radio host says against written sources. Use ONLY the sources below. \
Never use your own knowledge: if the sources do not say it, it is "insufficient", even when you \
believe it is true.

Sentences (numbered):
{sentences}

Sources (id: text):
{sources}

For every sentence that states an objective, checkable fact, return one finding. Facts are: who \
composed, wrote, sang, played, directed or released something; which film, album or work a piece \
belongs to; dates, numbers and events; how a piece was made or what led to it; and technical statements \
about a specific piece (its scale, key, instrumentation, structure). A comparison between people or \
works is a fact when it states a relation (influence, teacher, same period), not when it is the host's \
own way of putting the connection.

Do NOT return a finding for: the host's own impressions and descriptions of how music feels or sounds \
(mood, atmosphere, space, warmth, "simple", "slowly unfolds"); an invitation to listen for something; a \
transition; a sentence that only says a track is playing now, was just played or plays next, or only sums up \
the programme's own route in the host's words; a sentence that only names a track together with the artist \
the catalog credits for it (the catalog lines are a source for that, use them if you do return a finding).

verdict:
- "supported": a source states it. Give that source's id and a quote copied word for word, in the \
source's own script and without translating, from the source (at most 60 characters).
- "contradicted": a source states something different. Give its id and quote.
- "insufficient": no source states it. A name that merely appears near another name does not show who \
did what; the role (composer, lyricist, performer, director, release) must be stated. The catalog \
lines say only who is credited as performer; they say nothing about composers, lyricists or films.

Return JSON {{"findings": [{{"sentence": n, "verdict": "...", "source": "id", "quote": "..."}}]}}."""


class FactChecker:
    """Checks a radio script's factual sentences; see the module docstring."""

    def __init__(self, llm: FastStructuredProvider, *, profile: InferenceProfile = InferenceProfile.FAST) -> None:
        self._llm = llm
        self._profile = profile

    async def review(
        self,
        script: RadioScript,
        evidence: Sequence[Evidence],
        *,
        tracks: Sequence[KnownTrack] = (),
        route_labels: Sequence[str] = (),
        context: str = "",
        known_text: Sequence[Evidence] = (),
    ) -> FactReport:
        report = FactReport()
        sentences: list[tuple[int, int, str]] = []  # (block, index in block, text)
        for block_index, written in enumerate(script.blocks):
            for sentence_index, text in enumerate(split_sentences(written.text)):
                sentences.append((block_index, sentence_index, text))
        if not sentences:
            return report

        sources: dict[str, str] = {item.id: item.claim_or_excerpt for item in evidence}
        catalog = _catalog_lines(tracks, route_labels)
        if catalog:
            sources[CATALOG_SOURCE] = "\n".join(catalog)
        # A work named anywhere in the research is grounded as a name; whether a statement about
        # it is true is the checker's question, over the scoped sources only.
        corpus = "\n".join([*sources.values(), context, *(item.claim_or_excerpt for item in known_text)])
        known = _known_titles(tracks, route_labels)

        flagged: dict[int, SentenceIssue] = {}
        for number, (block, index, text) in enumerate(sentences):
            for name in unknown_titles(text, known, corpus):
                flagged[number] = SentenceIssue(
                    block,
                    index,
                    text,
                    "unknown_title",
                    f"“{text.strip()}” names 《{name}》, which is neither a track of this programme "
                    "nor a title that appears in the evidence. Use the track's Chinese title from "
                    "the slot context, or say 这首歌; do not make up a title.",
                )

        findings = await self._ask(sentences, sources)
        if findings is not None:
            report.model_checked = True
        by_sentence = {finding.sentence: finding for finding in findings or ()}

        for number, (block, index, text) in enumerate(sentences):
            if number in flagged:
                report.issues.append(flagged[number])
                continue
            finding = by_sentence.get(number)
            if finding is not None and finding.verdict == "not_factual":
                finding = None
            needs_source = must_be_supported(text)
            if findings is None:
                # The checker was unavailable: only what code can establish applies, and a
                # sentence with no source at all cannot be supported.
                if needs_source and not sources:
                    report.issues.append(_unsupported(block, index, text, "no_source"))
                continue
            if finding is None:
                if needs_source:
                    report.issues.append(_unsupported(block, index, text, "unchecked"))
                continue
            verdict, source_id = finding.verdict, finding.source.strip()
            if verdict == "supported":
                text_of_source = sources.get(source_id, "")
                if not text_of_source or not quote_in_source(finding.quote, text_of_source):
                    verdict = "insufficient"
                elif (families := role_families(text)) and (
                    families - {"performance"}
                    if source_id == CATALOG_SOURCE
                    else not any(
                        word in finding.quote for family in families for word in _ROLE_FAMILIES[family]
                    )
                ):
                    # The catalog names only the performer; any other source's quote must
                    # speak of the role the sentence claims.
                    verdict = "insufficient"
            if verdict == "supported" and _TITLE_IN_BRACKETS.search(text) and role_families(text):
                # An attribution about a named work must be backed by a quote that names the
                # work: "composer of another piece" does not show who wrote this one.
                if not any(
                    _squash(name) in _squash(finding.quote) for name in _TITLE_IN_BRACKETS.findall(text)
                ) and not _quote_names_title_variant(finding.quote, text, tracks):
                    verdict = "insufficient"
            if verdict == "supported":
                logger.info(
                    "fact_supported source=%s quote=%s", source_id[-8:], finding.quote.strip()[:80]
                )
                if source_id in {item.id for item in evidence}:
                    report.supported.setdefault(block, []).append(
                        ClaimSupport(
                            claim_type=ClaimType.FACT, claim=text.strip()[:500], evidence_ids=[source_id]
                        )
                    )
            elif verdict == "contradicted":
                report.issues.append(
                    SentenceIssue(
                        block,
                        index,
                        text,
                        "contradicted",
                        f"“{text.strip()}” is contradicted by the evidence"
                        + (f" (“{finding.quote.strip()}”)" if finding.quote else "")
                        + ". Say what the evidence says, or leave the sentence out.",
                    )
                )
            elif script.blocks[block].kind is RadioScriptBlockKind.OUTRO and not needs_source:
                # A closing only gathers the route the listener has heard, in the host's words;
                # without an attribution, a date or a made-up title, it is not cut for that.
                continue
            else:
                report.issues.append(_unsupported(block, index, text, "insufficient"))
        logger.info(
            "fact_check sentences=%d issues=%s supported=%d model_checked=%s",
            len(sentences),
            ",".join(issue.code for issue in report.issues) or "-",
            sum(len(items) for items in report.supported.values()),
            report.model_checked,
        )
        return report

    async def _ask(
        self, sentences: Sequence[tuple[int, int, str]], sources: dict[str, str]
    ) -> list[FactFinding] | None:
        if not sources:
            return None
        prompt = _PROMPT.format(
            sentences="\n".join(f"{number}. {text.strip()}" for number, (_b, _i, text) in enumerate(sentences)),
            sources="\n".join(f"[{source_id}]: {text}" for source_id, text in sources.items()),
        )
        result: object = None
        for attempt in range(2):
            try:
                result = await self._llm.structured(
                    prompt,
                    FactCheck,
                    transport=StructuredTransport.RESPONSES_JSON_SCHEMA,
                    profile=self._profile,
                    stage="fact_check",
                )
                break
            except Exception as error:  # noqa: BLE001 - an optional check must never stop the programme
                logger.warning(
                    "fact_check_unavailable attempt=%d error_type=%s", attempt + 1, type(error).__name__
                )
                if not isinstance(error, ProviderInvalidResponseError):
                    return None
        else:
            return None
        if not isinstance(result, FactCheck):
            logger.warning("fact_check_unavailable error_type=unexpected_output")
            return None
        return result.findings


def _unsupported(block: int, index: int, text: str, code: str) -> SentenceIssue:
    return SentenceIssue(
        block,
        index,
        text,
        code,
        f"“{text.strip()}” is not supported by the evidence. Say only what the evidence states "
        "(who composed, wrote, sang, directed or released something, dates, how it was made); "
        "if the evidence does not say it, leave the sentence out.",
    )


def without_flagged_sentences(
    script: RadioScript, report: FactReport, tracks: Sequence[KnownTrack] = ()
) -> RadioScript:
    """Remove the sentences that are still unsupported; a block left empty is dropped.

    The sentences that were found in a source are recorded as the block's ``claim_support``
    (internal: the listener never sees it).
    """

    drop: dict[int, set[int]] = {}
    for issue in report.issues:
        drop.setdefault(issue.block, set()).add(issue.sentence)
    blocks = []
    for block_index, block in enumerate(script.blocks):
        removed = drop.get(block_index)
        if removed:
            kept = [s for i, s in enumerate(split_sentences(block.text)) if i not in removed]
            logger.warning(
                "writer_sentences_dropped reason=unsupported_fact kind=%s dropped=%d kept=%d",
                block.kind.value,
                len(removed),
                len(kept),
            )
            text = "".join(kept).strip()
            if not text:
                continue
            # The spoken form was derived from the old text and would still say the removed
            # sentences, so it is derived again.
            spoken = to_spoken_form(text, tracks).tts_text
            block = block.model_copy(update={"text": text, "tts_text": spoken if spoken != text else None})
        claims = report.supported.get(block_index)
        if claims:
            block = block.model_copy(update={"claim_support": claims[:8]})
        blocks.append(block)
    return script.model_copy(update={"blocks": blocks})
