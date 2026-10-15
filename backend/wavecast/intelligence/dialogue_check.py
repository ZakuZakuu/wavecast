"""A light fact safety net for a two-host passage, against the story material it came from.

What decides, and what only helps:

* **The model (one Pro call) decides the semantics.**  It sees every sentence in the dialogue,
  the facts, the source title and the stretch of source text around each quote, and says per
  sentence whether the facts support it - including who said it, the qualifiers it adds
  ("first", "only", "always", "why") and whether a paraphrase is faithful.  A sentence is an
  *issue* only if it is "contradicted" or "insufficient": a substantive factual problem.
  Naturalness, impressions of the music and style are never a reason to send a passage back.
* **Code decides the structure, and nothing else.**  The cited fact ids exist in this material,
  the turn declared them in its ``fact_refs``, and the quote is a verbatim stretch of a cited
  fact's source text.  A supported verdict that fails one of these is an issue.
* **Pattern matching only points.**  Words that often need a closer look (said-by, first, only,
  roles, years) are shown to the model as a hint, and afterwards recorded as ``hints`` when the
  model's own quote does not carry them.  A hint is *unknown*, not a verdict: it never rejects
  a passage and never triggers a repair by itself.
* **The answer must be complete to count.**  One finding for every numbered sentence, none
  missing, repeated or out of range.  Otherwise there is no judgement at all (``model_checked``
  is false, exactly as if the call had failed): the caller refuses to voice a story on trust,
  and nothing is retried or repaired.  Inside a complete answer, ``not_factual`` is a valid
  judgement that a pattern match cannot overrule.

It makes one call and never retries; the passage's call budget is spent by the caller.  If the
call fails the passage has no judgement (``model_checked`` is false) and the caller decides -
a story is never voiced on trust.  It changes no text.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict

from wavecast.models.dialogue import DialogueBlock, DialogueIssue
from wavecast.models.story_material import MaterialFact, StoryMaterial
from wavecast.providers.profiles import InferenceProfile, StructuredTransport

from .fact_support import (
    must_be_supported,
    qualifiers_missing,
    quote_backs_roles,
    quote_in_source,
    roles_in,
    split_sentences,
    watch_notes,
)
from .fast_start import FastStructuredProvider

logger = logging.getLogger(__name__)


class SentenceFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sentence: int
    verdict: Literal["supported", "contradicted", "insufficient", "not_factual"]
    fact_ids: list[str]
    quote: str


class DialogueCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[SentenceFinding]


@dataclass
class DialogueCheckReport:
    # Substantive problems: the only thing that can send a turn to repair.
    issues: list[DialogueIssue] = field(default_factory=list)
    # Pattern-based pointers and gaps (see the module docstring): unknown, never a verdict.
    hints: list[DialogueIssue] = field(default_factory=list)
    # Per turn: the facts its supported sentences were found in.
    supported: dict[int, list[str]] = field(default_factory=dict)
    model_checked: bool = False

    def flagged_turns(self) -> dict[int, str]:
        """Turn index → what is wrong with it, for the repair step."""
        flagged: dict[int, list[str]] = {}
        for issue in self.issues:
            flagged.setdefault(issue.turn, []).append(issue.message)
        return {turn: " ".join(messages) for turn, messages in flagged.items()}


_PROMPT = """You check what two radio hosts say against written source facts. Use ONLY the facts \
below. Never use your own knowledge: if the facts do not state it, it is "insufficient", even when \
you believe it is true.

The dialogue is shown in order; judge each numbered sentence IN ITS CONTEXT. A question counts \
when it takes a fact for granted (a premise): judge the premise. An answer that completes the claim \
begun in the previous turn is judged together with it. Return exactly one finding for EVERY \
numbered sentence, none left out.

A FACT states something objective and checkable: who composed, wrote, sang, played or released \
something; dates, numbers, events; how something was made or what led to it; what someone said or \
did, including "for the first time", "only", "always", "says himself"; that one work or person \
influenced another; a cause ("so"); technical statements about a specific piece. Everything else is \
"not_factual": the hosts' impressions of how music sounds or feels, invitations to listen, \
transitions, "this plays next", and the editorial framing of a way to listen ("you could hear it \
as..."), which is a view and not a claim about the world. A sentence that mixes a view with a fact \
is a fact.

verdict for a fact:
- "supported": the facts say what the sentence says. A faithful paraphrase is supported; the \
wording does not have to match. Judge who and what: if the sentence says someone said, thinks, \
did or was first at something, the source (use its title and the surrounding text, which show who \
is speaking - for instance an interview answer is the interviewee's own words) must show that \
person, and any "first", "only", "always" or reason the sentence adds must be in the source too. \
Give the ids of the facts relied on and a quote copied word for word from one of their SOURCE \
TEXTS, in its own script, without translating (at most 60 characters); it only has to be a real \
stretch of that source text.
- "contradicted": a fact states something different. Give its id and quote.
- "insufficient": the facts do NOT state something the sentence asserts - another person, a \
degree, a reason, a date, a role. Use it only for a real factual gap; never for style, natural \
phrasing, an impression, or a harmless reordering of facts the source does state.
For everything else: "not_factual" (fact_ids [] and quote "").

A line marked "note" below a sentence points at words that often need a closer look; it is only a \
pointer, not a finding.

Facts (id, a gist for orientation only - quote the SOURCE TEXT, not the gist; "context" is the \
text around the source text, to see who is speaking):
{facts}

Dialogue:
{dialogue}

Return JSON {{"findings": [{{"sentence": n, "verdict": "supported|contradicted|insufficient|\
not_factual", "fact_ids": ["id"], "quote": "..."}}]}}."""


class DialogueFactChecker:
    def __init__(
        self, llm: FastStructuredProvider, *, profile: InferenceProfile = InferenceProfile.FAST
    ) -> None:
        self._llm = llm
        self._profile = profile

    async def review(self, block: DialogueBlock, material: StoryMaterial) -> DialogueCheckReport:
        report = DialogueCheckReport()
        sentences: list[tuple[int, int, str]] = []  # (turn, index in turn, text)
        for turn_index, spoken in enumerate(block.turns):
            for sentence_index, text in enumerate(split_sentences(spoken.text)):
                sentences.append((turn_index, sentence_index, text.strip()))
        if not sentences:
            return report

        findings = await self._ask(block, material, sentences)
        if findings is not None and not _covers_exactly(findings, len(sentences)):
            # An empty, short, repeated or out-of-range answer is not a judgement of this
            # dialogue: treat it like an unavailable check (no verdicts, nothing voiced on trust).
            logger.warning(
                "dialogue_fact_check_incomplete expected=%d returned=%d", len(sentences), len(findings)
            )
            findings = None
        report.model_checked = findings is not None
        by_sentence = {finding.sentence: finding for finding in findings or ()}

        for number, (turn, index, text) in enumerate(sentences):
            finding = by_sentence.get(number)
            if finding is None:
                # No judgement at all (the call failed, or its answer was incomplete): unknown.
                if must_be_supported(text):
                    report.hints.append(_hint(turn, index, text, "unchecked"))
                continue
            if finding.verdict == "not_factual":
                continue  # a complete answer's judgement: a pattern match cannot overrule it
            if finding.verdict == "contradicted":
                report.issues.append(
                    _issue(turn, index, text, "contradicted", f' (“{finding.quote.strip()}”)')
                )
                continue
            code = self._structural_problem(finding, material)
            if code is None and not set(finding.fact_ids) <= set(block.turns[turn].fact_refs):
                code = "undeclared_fact_ref"
            if code is not None:
                report.issues.append(_issue(turn, index, text, code))
                continue
            relied = report.supported.setdefault(turn, [])
            relied.extend(f for f in finding.fact_ids if f not in relied)
            # Pattern checks against the model's own quote: pointers for whoever reads the report.
            roles = roles_in(text)
            if roles and not quote_backs_roles(finding.quote, roles):
                report.hints.append(_hint(turn, index, text, "role_not_in_quote"))
            if qualifiers_missing(text, finding.quote):
                report.hints.append(_hint(turn, index, text, "qualifier_not_in_quote"))
        logger.info(
            "dialogue_fact_check sentences=%d issues=%s hints=%s model_checked=%s",
            len(sentences),
            ",".join(issue.code for issue in report.issues) or "-",
            ",".join(hint.code for hint in report.hints) or "-",
            report.model_checked,
        )
        return report

    @staticmethod
    def _structural_problem(finding: SentenceFinding, material: StoryMaterial) -> str | None:
        """Only what code can know for certain: the ids and the quote are real."""

        if finding.verdict != "supported":
            return "insufficient"
        facts = [material.fact(fact_id) for fact_id in finding.fact_ids]
        if not facts or any(fact is None for fact in facts):
            return "unknown_fact_id"
        if not any(fact is not None and quote_in_source(finding.quote, fact.quote) for fact in facts):
            return "quote_not_in_source"
        return None

    async def _ask(
        self,
        block: DialogueBlock,
        material: StoryMaterial,
        sentences: list[tuple[int, int, str]],
    ) -> list[SentenceFinding] | None:
        numbering: dict[int, list[str]] = {}
        for number, (turn, _index, text) in enumerate(sentences):
            lines = numbering.setdefault(turn, [])
            lines.append(f"  {number}. {text}")
            if notes := watch_notes(text):
                lines.append("     note: check against the source - " + " / ".join(notes[:4]))
        dialogue = "\n".join(
            f"Turn {turn_index} ({turn.speaker.value}):\n" + "\n".join(numbering.get(turn_index, []))
            for turn_index, turn in enumerate(block.turns)
        )
        cited = {ref for turn in block.turns for ref in turn.fact_refs}
        facts = "\n".join(_fact_block(fact, with_context=fact.fact_id in cited) for fact in material.facts)
        try:
            result = await self._llm.structured(
                _PROMPT.format(facts=facts, dialogue=dialogue),
                DialogueCheck,
                transport=StructuredTransport.RESPONSES_JSON_SCHEMA,
                profile=self._profile,
                stage="dialogue_fact_check",
            )
        except Exception as error:  # noqa: BLE001 - an optional check must never stop the programme
            logger.warning("dialogue_fact_check_unavailable error_type=%s", type(error).__name__)
            return None
        if not isinstance(result, DialogueCheck):
            logger.warning("dialogue_fact_check_unavailable error_type=unexpected_output")
            return None
        return result.findings


def _covers_exactly(findings: list[SentenceFinding], expected: int) -> bool:
    """One finding for every numbered sentence: none left out, none repeated, none out of range."""

    numbers = [finding.sentence for finding in findings]
    return len(numbers) == expected and set(numbers) == set(range(expected))


def _fact_block(fact: MaterialFact, *, with_context: bool) -> str:
    lines = [f"[{fact.fact_id}] gist: {fact.statement}"]
    if fact.source_title:
        lines.append(f"    source title: {fact.source_title}")
    lines.append(f"    source text: {fact.quote}")
    if with_context and fact.context:
        lines.append(f"    context: {fact.context}")
    return "\n".join(lines)


_MESSAGES = {
    "contradicted": "is contradicted by the facts",
    "insufficient": "asserts something the facts do not state",
    "unknown_fact_id": "relies on a fact id that is not in the material",
    "quote_not_in_source": "has a supporting quote that is not in the fact's source text",
    "undeclared_fact_ref": "rests on facts that the turn's fact_refs do not list",
}
_HINTS = {
    "unchecked": "was not judged against the facts",
    "role_not_in_quote": "names a role (composer, arranger, singer...) the model's quote does not state",
    "qualifier_not_in_quote": "adds a qualifier (first time, only, who said it, why...) the model's quote does not carry",
}


def _issue(turn: int, sentence: int, text: str, code: str, extra: str = "") -> DialogueIssue:
    return DialogueIssue(
        turn=turn,
        sentence=sentence,
        code=code,
        message=(
            f"“{text[:120]}” {_MESSAGES[code]}{extra}. "
            "Keep what the facts support; reword only the part they do not state."
        ),
    )


def _hint(turn: int, sentence: int, text: str, code: str) -> DialogueIssue:
    return DialogueIssue(
        turn=turn,
        sentence=sentence,
        code=code,
        message=f"“{text[:120]}” {_HINTS[code]} (a pointer, not a finding).",
    )
