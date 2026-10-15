"""Checking the host's factual sentences against the sources the application actually holds.

The Writer is told to use only the scoped evidence, but nothing used to check that it did: a
sentence such as "the song was composed by X" could rest on a model's memory (or on a name
that merely appears near the subject in a web page) and still be spoken.  This module checks
each factual sentence before it is voiced:

* Code decides what must be supported: attribution and creation words (who composed, wrote,
  sang, directed, released), years, and the names of works in 《》.  A sentence the checker
  calls "not factual" is still checked when it carries one of those markers.
* One short model call returns a judgement for every sentence: a fact is "supported",
  "contradicted" or "insufficient" (with the source it relies on and a quote), anything else
  is "not_factual".  A sentence it leaves out is asked about once more, and is never taken as
  "not a fact".  The quote must be found in that source (code checks), and must carry the
  qualifiers the sentence adds ("first", "says himself", "so", "influenced", instruments),
  so the checker cannot supply evidence from its own memory or let one keyword stand for a
  whole claim.  The sources are the scoped evidence plus the catalog's own lines.
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
from wavecast.text_identity import base_title_key, canonical_name

from .fast_start import FastStructuredProvider
from .models import ClaimSupport, ClaimType, Evidence, RadioScript

logger = logging.getLogger(__name__)

CATALOG_SOURCE = "catalog"
_SENTENCE = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]*|\n+")
_TITLE_IN_BRACKETS = re.compile(r"《([^》]{1,40})》")
_GENERIC_TITLES = frozenset({"这首歌", "这首曲子", "这支曲子", "这首", "这支曲子"})
_IGNORED = re.compile(r"[\s，。！？、；：,.!?;:“”\"'‘’《》「」『』（）()\-—…·]+")
_MIN_QUOTE_CHARS = 4

# Who did what, one word family per role.  A sentence that claims a role is supported only by a
# quote that speaks of that same role: "arranged" does not show "composed", and being credited
# on a recording does not show who sang on it.  ``creation`` is the loose "wrote / made" claim,
# which any of the creative roles can back.
_ROLES: dict[str, tuple[str, ...]] = {
    "composer": ("作曲", "谱曲"),
    "arranger": ("编曲",),
    "score": ("配乐",),
    "lyricist": ("作词", "填词", "词作"),
    "vocal": ("演唱", "主唱", "领唱", "唱的是", "唱的", "唱了", "献唱"),
    "instrumental": ("演奏", "弹奏", "独奏"),
    "director": ("导演", "执导"),
    "cast": ("主演",),
    "release": ("发行", "首映", "上映", "公映", "出版", "票房"),
    "award": ("获奖", "荣获", "入围"),
    "creation": ("创作", "写成", "写了", "写出", "谱写"),
}
_CREATIVE_ROLES = ("composer", "arranger", "score", "lyricist", "creation")
_ROLE_TRIGGER = re.compile(
    "|".join(re.escape(word) for words in _ROLES.values() for word in words)
    + r"|出自|寄给|写给|参与|制作|改编|根据|诞生|灵感"
)
# Biographical turns, self-attribution, influence and music-theory statements are facts too,
# whatever the checker calls them; "转变" or "延续" alone are not (a host may say them as a view).
_FACT_TRIGGER = re.compile(
    r"第一次|首次|头一次|初次|首度|第一回|自己说|自己讲|曾说|说过|曾表示|坦言|自述|亲口|"
    r"影响了|影响着|启发了|奠定|开创|二五一|二级|五级|一级|AABC|和声|和弦|调式|调性|大调|小调|转调|曲式|BPM"
)


def _alternatives(words: Sequence[str]) -> re.Pattern[str]:
    return re.compile("|".join(re.escape(canonical_name(word)) for word in words))


# A sentence that adds one of these to a claim needs a quote that says it as well: a source that
# only names the work does not show that it was "the first", "said by himself", "why", or played
# on a "small band".  (sentence words, words that carry the same qualifier in a quote)
_QUALIFIERS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "first",
        ("第一次", "首次", "头一次", "初次", "首度", "第一回"),
        ("初めて", "はじめて", "初の", "初次", "第一次", "第一回", "首次", "首度", "头一次", "first", "ようやく"),
    ),
    (
        "self-said",
        ("自己说", "自己讲", "曾说", "说过", "曾表示", "坦言", "自述", "亲口", "他说", "她说"),
        ("说", "語", "話", "述", "言", "表示", "談", "コメント", "インタビュー", "said", "told", "says", "「", "“", '"'),
    ),
    (
        "cause",
        ("所以", "因此", "因而", "从而", "正因", "导致", "使得", "才让", "才能", "才会", "因为", "由于"),
        ("所以", "ため", "ので", "から", "ゆえ", "故", "因", "由于", "为了", "によって", "ことで", "結果", "导", "導",
         "せい", "おかげ", "because", "so that", "thus", "therefore", "led to", "result", "why"),
    ),
    (
        "influence",
        ("影响了", "影响着", "影响后", "启发了", "奠定", "开创", "后来的", "此后的"),
        ("影響", "影响", "啓発", "启发", "インスパイア", "influence", "inspired", "手本", "模範", "基礎", "後の", "後に",
         "后来", "later", "legacy", "先駆", "pioneer"),
    ),
    ("period", ("一年里", "一年中", "一年内", "每年"), ("年", "year", "annual")),
    (
        "always",
        ("一直", "始终", "总是", "从未", "从来没", "从不", "一向"),
        ("いつも", "ずっと", "常に", "一貫", "一直", "始终", "总是", "从未", "从来", "从不", "決して", "一度も",
         "never", "always", "ever"),
    ),
    ("only", ("唯一", "只有", "仅有"), ("唯一", "only", "のみ", "だけ", "ただ", "仅", "只有", "sole")),
    (
        "whole",
        ("所有", "全部", "整个", "每首", "每部"),
        ("すべて", "全て", "全部", "所有", "整个", "全体", "全", "all", "every", "each", "entire", "whole"),
    ),
)
_QUALIFIER_PATTERNS = tuple(
    (name, _alternatives(sentence_words), _alternatives(quote_words))
    for name, sentence_words, quote_words in _QUALIFIERS
)
# Instruments and ensembles named in a sentence must be named by the quote too.
_INSTRUMENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("小乐队", ("小乐队", "小編成", "少人数", "バンド", "small", "combo", "ensemble", "chamber", "室内")),
    ("大乐队", ("大乐队", "大編成", "オーケストラ", "管弦楽", "交響", "orchestra", "symphon", "乐团", "管弦")),
    ("合唱", ("合唱", "コーラス", "混声", "choir", "chorus", "choral")),
    ("定音鼓", ("定音鼓", "ティンパニ", "timpani")),
    ("弦乐", ("弦乐", "弦", "ストリングス", "string")),
    ("钢琴", ("钢琴", "ピアノ", "piano")),
    ("小提琴", ("小提琴", "ヴァイオリン", "バイオリン", "violin")),
    ("吉他", ("吉他", "ギター", "guitar")),
    ("萨克斯", ("萨克斯", "サックス", "sax")),
    ("小号", ("小号", "トランペット", "trumpet")),
    ("长笛", ("长笛", "フルート", "flute")),
    ("合成器", ("合成器", "シンセ", "synth")),
    ("贝斯", ("贝斯", "ベース", "bass")),
)
_INSTRUMENT_PATTERNS = tuple((word, _alternatives(quote_words)) for word, quote_words in _INSTRUMENTS)


def qualifiers_missing(sentence: str, quote: str) -> list[str]:
    """Qualifiers the sentence adds to its claim that the quote does not carry.

    A quote that states a different, narrower or plainer thing than the sentence does not
    support the sentence, even when both name the same work or person.
    """

    folded = canonical_name(quote)
    missing = [
        name
        for name, in_sentence, in_quote in _QUALIFIER_PATTERNS
        if in_sentence.search(sentence) and not in_quote.search(folded)
    ]
    missing += [
        word
        for word, in_quote in _INSTRUMENT_PATTERNS
        if word in sentence and not in_quote.search(folded)
    ]
    return missing


# A sentence that starts like this leans on the one before it.
_DANGLING_START = re.compile(
    r"^\s*(?:因此|所以|于是|但是?|可是|不过|而且?|并且|同时|此外|另外|然后|接着|其中|同样|"
    r"也|还|又|他们?|她们?|它们?|其|该|此|这也|这就|这样|这些|那|这一首[，,]|这首[，,])"
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


def quote_in_source(quote: str, source: str) -> bool:
    """True when the quote is a verbatim stretch of the source.

    Script variants, spacing and punctuation are ignored (a quote copied from a Traditional
    Chinese page still matches), but the words themselves must be contiguous and complete, so
    a quote with a negation removed does not match.
    """

    squashed = _squash(quote)
    return len(squashed) >= _MIN_QUOTE_CHARS and squashed in _squash(source)


# Words that, in a quoted source, state a role in the ways other languages put it (Japanese
# pages say 歌唱, 歌われる, 歌詞).  They are matched after script variants are folded.
_QUOTE_ROLE_WORDS: dict[str, tuple[str, ...]] = {
    "lyricist": ("歌词",),
    "vocal": ("歌唱", "歌われ", "歌って", "歌わ", "唱:", "唱：", "歌:", "歌：", "vocal"),
}


def roles_in(text: str, *, quote: bool = False) -> set[str]:
    """The roles a sentence claims, or (``quote=True``) a source line states, script-folded."""

    folded = canonical_name(text) if quote else text
    found = {role for role, words in _ROLES.items() if any(word in folded for word in words)}
    if quote:
        found |= {
            role for role, words in _QUOTE_ROLE_WORDS.items() if any(word in folded for word in words)
        }
    return found


def quote_backs_roles(quote: str, roles: set[str]) -> bool:
    """Every role the sentence claims is spoken of, as that role, in the quote."""

    quoted = roles_in(quote, quote=True)
    return all(
        role in quoted or (role == "creation" and quoted & set(_CREATIVE_ROLES)) for role in roles
    )


def must_be_supported(sentence: str) -> bool:
    """Attributions, creation stories and dated statements are never taken on trust."""

    return (
        bool(_ROLE_TRIGGER.search(sentence))
        or bool(_FACT_TRIGGER.search(sentence))
        or bool(years_in(sentence))
    )


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


_ARTIST_SPLIT = re.compile(r"\s*(?:,|，|、|/|&|;|；|\bfeat\.?|\bft\.?)\s*", re.IGNORECASE)


def credited_people(artists: Sequence[str]) -> list[str]:
    """The individual names in artist credits ("久石譲, 奥户巴寿" -> both), squashed for comparison."""

    names: list[str] = []
    for credit in artists:
        for part in _ARTIST_SPLIT.split(credit):
            key = _squash(part)
            if len(key) >= 2 and key not in names:
                names.append(key)
    return names


def people_missing_from_quote(text: str, quote: str, people: Sequence[str]) -> list[str]:
    """People the sentence names (among those the programme knows) that the quote does not.

    "作曲是久石让" backed by a line that says "作曲：木村弓" has the right role and the wrong person.
    """

    squashed_text, squashed_quote = _squash(text), _squash(quote)
    return [name for name in people if name in squashed_text and name not in squashed_quote]


def _names_track(text: str, track: KnownTrack) -> bool:
    """``text`` names the track: its catalog title, its Chinese title, or the title without a version tag."""

    squashed = _squash(text)
    return any(
        len(key) >= 2 and key in squashed
        for key in (_squash(track.title), _squash(base_title_key(track.title)), _squash(track.spoken_title or ""))
    )


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

Return exactly one finding for EVERY numbered sentence, none left out.

Classify each sentence first.
A FACT states something objective and checkable: who composed, wrote, sang, played, directed or \
released something; which film, album or work a piece belongs to; dates, numbers and events; how a \
piece was made or what led to it; what someone said, felt or did, including "for the first time", \
"only", "always", "says himself" and similar turns in a life or career; that one work or person \
influenced another; why something is the way it is (a cause or a "so"); technical statements about a \
specific piece (its scale, key, chord progression, form, instrumentation). A comparison between \
people or works is a fact when it states a relation (influence, teacher, same period), not when it is \
the host's own way of putting the connection.
Everything else is "not_factual": the host's own impressions of how music feels or sounds (mood, \
atmosphere, space, warmth, "simple", "slowly unfolds"); an invitation to listen for something; a \
transition; a sentence that only says a track is playing now, was just played or plays next, or only \
sums up the programme's own route in the host's words; a sentence that only names a track together \
with the artist the catalog credits for it. A sentence that mixes an impression with a fact is a fact.

verdict for a fact:
- "supported": ONE source states the WHOLE sentence. Give that source's id and a quote copied word for \
word, in the source's own script and without translating (at most 60 characters). The quote itself must \
say who or what, the relation, and every qualifier the sentence adds (first time, only, always, \
who said it, why, which version, how many, which instruments). If the sentence says more than the \
quote does, even one connecting reason or one adjective of degree, it is "insufficient"; a name that \
merely appears near another name proves nothing, and a source about the work in general does not prove \
something about a particular recording or person.
- "contradicted": a source states something different. Give its id and quote.
- "insufficient": no source states it as the sentence does. The role (composer, lyricist, performer, \
director, release) must be stated. The catalog lines say only who is credited on a recording; they \
say nothing about composers, lyricists or films.
verdict for everything else: "not_factual".

Sources (id: text):
{sources}

Sentences (numbered):
{sentences}

Return JSON {{"findings": [{{"sentence": n, "verdict": "supported|contradicted|insufficient|not_factual", \
"source": "id", "quote": "..."}}]}}."""


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
        focus_tracks: Sequence[KnownTrack] = (),
        other_tracks: Sequence[KnownTrack] = (),
    ) -> FactReport:
        report = FactReport()
        sentences: list[tuple[int, int, str]] = []  # (block, index in block, text)
        for block_index, written in enumerate(script.blocks):
            for sentence_index, text in enumerate(split_sentences(written.text)):
                sentences.append((block_index, sentence_index, text))
        if not sentences:
            return report

        # A stable order (by id, the catalog last) keeps the long source block identical between
        # the checks of one chapter, so the provider's prompt cache can serve it.
        sources: dict[str, str] = {
            item.id: item.claim_or_excerpt for item in sorted(evidence, key=lambda item: item.id)
        }
        catalog = _catalog_lines(tracks, route_labels)
        if catalog:
            sources[CATALOG_SOURCE] = "\n".join(catalog)
        # A work named anywhere in the research is grounded as a name; whether a statement about
        # it is true is the checker's question, over the scoped sources only.
        corpus = "\n".join([*sources.values(), context, *(item.claim_or_excerpt for item in known_text)])
        known = _known_titles(tracks, route_labels)
        people = credited_people(
            [track.artist for track in tracks] + [label.split(" - ", 1)[0] for label in route_labels]
        )

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
            # A sentence the checker left out is not "not a fact": ask about those once more.
            unjudged = {number for number in range(len(sentences))} - {f.sentence for f in findings}
            unjudged -= set(flagged)
            if unjudged:
                logger.warning("fact_check_unjudged count=%d of=%d", len(unjudged), len(sentences))
                findings = [*findings, *(await self._ask(sentences, sources, only=unjudged) or [])]
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
                # The checker was unavailable.  What needs a source cannot be shown to have
                # one, so it is left out; the rest goes on unchecked and the music continues.
                if needs_source:
                    report.issues.append(_unsupported(block, index, text, "unchecked"))
                continue
            if finding is None:
                # Still without a judgement after the second ask (or called not factual while
                # carrying a marker): it cannot be shown to be harmless, so it does not stay.
                if needs_source or number not in by_sentence:
                    report.issues.append(_unsupported(block, index, text, "unchecked"))
                continue
            verdict, source_id = finding.verdict, finding.source.strip()
            if verdict == "supported":
                text_of_source = sources.get(source_id, "")
                roles = roles_in(text)
                if not text_of_source or not quote_in_source(finding.quote, text_of_source):
                    verdict = "insufficient"
                elif roles and (
                    source_id == CATALOG_SOURCE  # the catalog names a credit, never a role
                    or not quote_backs_roles(finding.quote, roles)
                ):
                    verdict = "insufficient"
            if verdict == "supported" and qualifiers_missing(text, finding.quote):
                # The quote names the same thing but not what the sentence adds to it.
                verdict = "insufficient"
            if verdict == "supported" and _TITLE_IN_BRACKETS.search(text) and roles_in(text):
                # An attribution about a named work must be backed by a quote that names the
                # work: "composer of another piece" does not show who wrote this one.
                if not any(
                    _squash(name) in _squash(finding.quote) for name in _TITLE_IN_BRACKETS.findall(text)
                ) and not _quote_names_title_variant(finding.quote, text, tracks):
                    verdict = "insufficient"
            if verdict == "supported" and roles_in(text) and people_missing_from_quote(text, finding.quote, people):
                # The right role, but a different person: the line does not say this person did it.
                verdict = "insufficient"
            if verdict == "supported" and roles_in(text):
                # A credit about a track of this programme must be read off a line naming that
                # track: the composer of the film it belongs to is not the composer of the song.
                named = [track for track in tracks if _names_track(text, track)]
                if named and not any(_names_track(finding.quote, track) for track in named):
                    verdict = "insufficient"
            if verdict == "supported" and focus_tracks and other_tracks:
                # A statement that rests on a source about another song of the programme is not
                # about the song this slot is for, whatever the sentence calls it.
                lead = f"{finding.quote}\n{sources.get(source_id, '')[:150]}"
                other = next((track for track in other_tracks if _names_track(lead, track)), None)
                if other is not None and not any(_names_track(lead, track) for track in focus_tracks):
                    focus_names = "、".join(track.spoken_title or track.title for track in focus_tracks)
                    report.issues.append(
                        SentenceIssue(
                            block,
                            index,
                            text,
                            "wrong_subject",
                            f"“{text.strip()}” rests on a source about “{other.title}”, but this slot "
                            f"is between {focus_names}. Talk about the tracks named in the slot "
                            "context, or leave the sentence out.",
                        )
                    )
                    continue
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
        self,
        sentences: Sequence[tuple[int, int, str]],
        sources: dict[str, str],
        *,
        only: set[int] | None = None,
    ) -> list[FactFinding] | None:
        if not sources:
            return None
        # Rules and sources come first and are the same for every ask about a chapter; only the
        # sentences, last, change.
        prompt = _PROMPT.format(
            sources="\n".join(f"[{source_id}]: {text}" for source_id, text in sources.items()),
            sentences="\n".join(
                f"{number}. {text.strip()}"
                for number, (_b, _i, text) in enumerate(sentences)
                if only is None or number in only
            ),
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


def similar_claim(left: str, right: str) -> bool:
    """Two statements that overlap by half or more of the shorter one say the same thing."""

    def grams(value: str) -> set[str]:
        squashed = _squash(value)
        return {squashed[i : i + 2] for i in range(len(squashed) - 1)}

    a, b = grams(left), grams(right)
    return bool(a and b) and len(a & b) / min(len(a), len(b)) >= 0.5


def with_carried_risks(script: RadioScript, report: FactReport, other: FactReport) -> FactReport:
    """``report`` plus the sentences of ``script`` that say what another draft was found wrong.

    When a rewrite is rejected and the earlier draft is kept, the rewrite's check may still have
    found that a claim is contradicted or unsupported.  That finding must not be forgotten just
    because the sentence in the kept draft was judged differently: the two checks disagree, and
    the claim stays out.  Sentences are matched by what they say, never by their number.
    """

    risky = [issue.text for issue in other.issues if issue.code in {"contradicted", "insufficient"}]
    if not risky:
        return report
    known = {(issue.block, issue.sentence) for issue in report.issues}
    carried: list[SentenceIssue] = []
    for block_index, block in enumerate(script.blocks):
        for sentence_index, text in enumerate(split_sentences(block.text)):
            if (block_index, sentence_index) in known:
                continue
            if any(similar_claim(text, other_text) for other_text in risky):
                logger.warning("fact_check_risk_carried block=%d sentence=%d", block_index, sentence_index)
                carried.append(
                    SentenceIssue(
                        block_index,
                        sentence_index,
                        text,
                        "carried",
                        f"“{text.strip()}” says what a later check found contradicted or unsupported.",
                    )
                )
    if not carried:
        return report
    return FactReport(
        issues=[*report.issues, *carried], supported=report.supported, model_checked=report.model_checked
    )


def _kept_sentences(sentences: Sequence[str], removed: set[int]) -> list[str]:
    """What is left after the removed sentences, without sentences that lost their context.

    A sentence that leans on the one before it ("因此…", "他…", "同样…") is removed too when
    that one is gone; if nothing coherent is left, the block is skipped by the caller.
    """

    kept: list[str] = []
    previous_removed = False
    for index, sentence in enumerate(sentences):
        if index in removed:
            previous_removed = True
            continue
        if previous_removed and _DANGLING_START.match(sentence):
            continue  # still "removed" for the next sentence's sake
        previous_removed = False
        kept.append(sentence)
    return kept


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
            kept = _kept_sentences(split_sentences(block.text), removed)
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
