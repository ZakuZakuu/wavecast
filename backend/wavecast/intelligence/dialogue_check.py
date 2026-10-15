"""Fact check for a two-host passage, against the story material it was written from.

The unit is the sentence, judged *in the dialogue*: the checker sees every turn in order, so a
question's factual premise ("why did he stay with Mandarin so long?") and an answer that only
completes the claim of the turn before are judged with their context, not as stray fragments.
Every sentence must come back with a judgement; one left out is treated as unchecked, never as
harmless.  The checker names the facts it relies on and copies a quote; code verifies all of it:

* the cited fact ids exist in this material, and the turn declared them in its ``fact_refs``;
* the quote is a verbatim stretch of a cited fact's source text;
* the quote carries the role the sentence claims (composed ≠ arranged ≠ sang) and every
  qualifier it adds (first time, only, always, who said it, why, instruments).

It makes one call and never retries: the passage's call budget is spent by the caller.  If the
call fails, sentences that must be supported are reported as unchecked (the passage will not
be voiced on trust).  It changes no text.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict

from wavecast.models.dialogue import DialogueBlock, DialogueIssue
from wavecast.models.story_material import StoryMaterial
from wavecast.providers.profiles import InferenceProfile, StructuredTransport

from .fact_support import (
    must_be_supported,
    qualifiers_missing,
    quote_backs_roles,
    quote_in_source,
    roles_in,
    split_sentences,
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
    issues: list[DialogueIssue] = field(default_factory=list)
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
- "supported": the cited facts' source text states the WHOLE sentence. Give the ids of the facts \
relied on and a quote copied word for word from one of their source texts, in its own script, \
without translating (at most 60 characters). The quote itself must say who or what, the relation, \
and every qualifier the sentence adds (first time, only, always, who said it, why, which version). \
If the sentence says more than the quote does, even one adjective of degree ("more mature") or one \
connecting reason, it is "insufficient".
- "contradicted": a fact states something different. Give its id and quote.
- "insufficient": no fact states it as the sentence does.
For everything else: "not_factual" (fact_ids [] and quote "").

Facts (id, a gist for orientation only - quote the source text, not the gist):
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
        report.model_checked = findings is not None
        by_sentence = {finding.sentence: finding for finding in findings or ()}

        for number, (turn, index, text) in enumerate(sentences):
            needs_source = must_be_supported(text)
            if findings is None:
                if needs_source:
                    report.issues.append(_issue(turn, index, text, "unchecked"))
                continue
            finding = by_sentence.get(number)
            if finding is None:
                # Left out: never assumed harmless.
                report.issues.append(_issue(turn, index, text, "unchecked"))
                continue
            if finding.verdict == "not_factual":
                if needs_source:
                    report.issues.append(_issue(turn, index, text, "unchecked"))
                continue
            if finding.verdict == "contradicted":
                report.issues.append(
                    _issue(turn, index, text, "contradicted", f' (“{finding.quote.strip()}”)')
                )
                continue
            code = self._why_not_supported(text, finding, material)
            if code is None and not set(finding.fact_ids) <= set(block.turns[turn].fact_refs):
                code = "undeclared_fact_ref"
            if code is not None:
                report.issues.append(_issue(turn, index, text, code))
                continue
            relied = report.supported.setdefault(turn, [])
            relied.extend(f for f in finding.fact_ids if f not in relied)
        logger.info(
            "dialogue_fact_check sentences=%d issues=%s model_checked=%s",
            len(sentences),
            ",".join(issue.code for issue in report.issues) or "-",
            report.model_checked,
        )
        return report

    @staticmethod
    def _why_not_supported(
        text: str, finding: SentenceFinding, material: StoryMaterial
    ) -> str | None:
        if finding.verdict != "supported":
            return "insufficient"
        facts = [material.fact(fact_id) for fact_id in finding.fact_ids]
        if not facts or any(fact is None for fact in facts):
            return "unknown_fact_id"
        if not any(fact is not None and quote_in_source(finding.quote, fact.quote) for fact in facts):
            return "quote_not_in_source"
        roles = roles_in(text)
        if roles and not quote_backs_roles(finding.quote, roles):
            return "role_not_in_quote"
        # Whose own words the cited source is, when the source itself shows it (an interview
        # answer): only then may "he said ..." rest on a quote that lacks the saying word.
        speakers = {
            fact.own_words_of
            for fact in facts
            if fact is not None and quote_in_source(finding.quote, fact.quote)
        }
        own = speakers.pop() if len(speakers) == 1 else None
        if qualifiers_missing(text, finding.quote, own_words_of=own):
            return "qualifier_not_in_quote"
        return None

    async def _ask(
        self,
        block: DialogueBlock,
        material: StoryMaterial,
        sentences: list[tuple[int, int, str]],
    ) -> list[SentenceFinding] | None:
        numbering: dict[int, list[str]] = {}
        for number, (turn, _index, text) in enumerate(sentences):
            numbering.setdefault(turn, []).append(f"  {number}. {text}")
        dialogue = "\n".join(
            f"Turn {turn_index} ({turn.speaker.value}):\n" + "\n".join(numbering.get(turn_index, []))
            for turn_index, turn in enumerate(block.turns)
        )
        facts = "\n".join(
            f"[{fact.fact_id}] gist: {fact.statement}\n    source text: {fact.quote}"
            for fact in material.facts
        )
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


_MESSAGES = {
    "unchecked": "has not been shown to be supported by the facts",
    "contradicted": "is contradicted by the facts",
    "insufficient": "is not stated by the facts as it is said",
    "unknown_fact_id": "relies on a fact id that is not in the material",
    "quote_not_in_source": "has a supporting quote that is not in the fact's source text",
    "role_not_in_quote": "claims a role (composer, arranger, singer...) the quote does not state",
    "qualifier_not_in_quote": "adds a qualifier (first time, only, why, who said it...) the quote does not carry",
    "undeclared_fact_ref": "rests on facts that the turn's fact_refs do not list",
}


def _issue(turn: int, sentence: int, text: str, code: str, extra: str = "") -> DialogueIssue:
    return DialogueIssue(
        turn=turn,
        sentence=sentence,
        code=code,
        message=f"“{text[:120]}” {_MESSAGES[code]}{extra}. Say only what the facts state, or leave it out.",
    )
