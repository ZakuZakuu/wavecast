"""The ``material`` role: distil shared story material from the programme's evidence.

One bounded model call reads the evidence the application already holds and proposes facts, each
with the evidence it rests on and a verbatim quote.  Code then decides what stays: a fact whose
evidence is unknown, whose quote is not a stretch of that evidence, whose statement adds a
qualifier or a role its quote does not carry, or that is about another recording than the
story's, is dropped; catalogue housekeeping is moved to ``backstage``.  Fact ids are assigned
here, never taken from the model.  The step writes no dialogue.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict

from wavecast.editorial import material_editorial_context
from wavecast.models.story_material import (
    MAX_MATERIAL_FACTS,
    StoryMaterial,
    StoryScope,
)
from wavecast.programme_date import programme_date
from wavecast.providers.errors import ProviderInvalidResponseError
from wavecast.providers.profiles import InferenceProfile, StructuredTransport

from .fact_support import (
    qualifiers_missing,
    quote_backs_roles,
    quote_in_source,
    roles_in,
)
from .fast_start import FastStructuredProvider
from .models import Evidence
from .time_guard import has_relative_time
from .track_research import _CATALOGUE_TRIVIA

logger = logging.getLogger(__name__)

MIN_VERIFIED_FACTS = 2
_MAX_EVIDENCE_CHARS = 900
_MAX_EVIDENCE_ITEMS = 12


class DraftFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str
    evidence_id: str
    quote: str
    scope: Literal["recording", "album", "background"]
    subject: str
    version_scope: str | None


class StoryMaterialDraft(BaseModel):
    """What the model returns.  Identity, verification and the fact ids are the application's."""

    model_config = ConfigDict(extra="forbid")

    subject: str
    scope: Literal["recording", "album", "background"]
    central_question: str
    facts: list[DraftFact]
    editorial_angle: str | None
    do_not_infer: list[str]
    backstage: list[str]


_PROMPT = """You prepare the shared factual material for one passage of a music radio programme. \
Two hosts will later talk about it; you do NOT write their lines.

Use ONLY the evidence below. Never add anything from your own knowledge.

Return:
- subject: whom or what the passage is about; scope: recording, album or background (the person and period).
- central_question: the one question the passage can answer, in the listener's words.
- facts: up to {max_facts}, each a checkable statement the evidence makes, with the id of the ONE \
evidence item it rests on and a quote copied word for word from that item (script as written, at \
most 120 characters, long enough to carry who/what, the relation and every qualifier the statement \
adds: first time, only, always, who said it, why). statement must say no more than its quote. scope \
says what the statement is about; subject names whom/what it is about; version_scope names the \
recording or release it holds for, or null when it is not tied to one.
- editorial_angle: why this suits the programme, as a judgement of the editor (not a fact), or null.
- do_not_infer: relations or claims the evidence does NOT establish and the hosts must not make.
- backstage: housekeeping that must never be spoken (catalogue numbers, source remarks).

Select material that helps the listener understand the music, the programme subject or the \
connection to the focus recordings. Prefer a creative decision, a collaboration, a turning point \
or a concrete musical detail. Leave out personal-life trivia with no clear musical relevance. \
Each fact should add something distinct; do not collect several articles saying a song is a classic.
Write statements as the content itself, in natural Simplified Chinese, not as a digest of articles. \
Source identity and publication dates belong in backstage, not in statements. Retain attribution \
when it matters: an artist's own words, a critic's particular interpretation or a disputed claim \
must not become an undisputed fact. Ordinary established facts need no "an article says" wrapper.

Programme date: {today}. An evidence item may carry its publication date in parentheses; the time a page \
was fetched is not a publication date. Resolve relative time (最近, 上个月, 今年, "last month"...) \
against the source's publication date, not today's date. Write a supported historical statement \
without implying present-day recency, or leave the fact out. Historical wording such as \
"2006年发行的新专辑" is fine when the evidence supports it. Do not merely \
delete "recently" while retaining "new" or "latest". A source's publication date is not the date \
of the event it describes; use an event date only when supported, and only if it helps the story. \
Whether the subject is alive or has died is only what \
the evidence says; if it does not say, do not state it either way, and speak of a person who has died in \
the past tense.

Focus recordings: {recordings}
Subject hint: {subject}
{editorial_context}

Evidence (id: text):
{evidence}"""


class StoryMaterialService:
    def __init__(
        self, llm: FastStructuredProvider, *, profile: InferenceProfile = InferenceProfile.SYNTHESIS
    ) -> None:
        self._llm = llm
        self._profile = profile

    async def extract(
        self,
        evidence: Sequence[Evidence],
        *,
        story_id: str,
        subject: str,
        recording_refs: Sequence[str] = (),
        programme_brief: str = "",
        editorial_goal: str = "",
    ) -> StoryMaterial | None:
        """The verified material, or ``None`` when too little of it survives verification.

        Provider failures propagate (the caller decides whether the passage is skipped);
        cancellation is never swallowed.
        """

        usable = [item for item in evidence if item.claim_or_excerpt.strip()][:_MAX_EVIDENCE_ITEMS]
        if not usable:
            return None
        draft = await self._ask(usable, subject, recording_refs, programme_brief, editorial_goal)
        return verify_material(
            draft, usable, story_id=story_id, recording_refs=recording_refs
        )

    async def _ask(
        self,
        evidence: Sequence[Evidence],
        subject: str,
        recording_refs: Sequence[str],
        programme_brief: str = "",
        editorial_goal: str = "",
    ) -> StoryMaterialDraft:
        prompt = _PROMPT.format(
            today=programme_date(),
            max_facts=MAX_MATERIAL_FACTS,
            recordings=", ".join(recording_refs) or "(none given)",
            subject=subject,
            editorial_context=material_editorial_context(programme_brief, editorial_goal),
            evidence="\n".join(
                f"[{item.id}]{f' (published {item.published_at})' if item.published_at else ''}: "
                f"{item.claim_or_excerpt[:_MAX_EVIDENCE_CHARS]}"
                for item in sorted(evidence, key=lambda e: e.id)
            ),
        )
        result = await self._llm.structured(
            prompt,
            StoryMaterialDraft,
            transport=StructuredTransport.RESPONSES_JSON_SCHEMA,
            profile=self._profile,
            stage="story_material",
        )
        if not isinstance(result, StoryMaterialDraft):
            raise ProviderInvalidResponseError("story material step returned invalid output")
        return result


def verify_material(
    draft: StoryMaterialDraft,
    evidence: Sequence[Evidence],
    *,
    story_id: str,
    recording_refs: Sequence[str] = (),
) -> StoryMaterial | None:
    by_id = {item.id: item for item in evidence}
    facts: list[dict[str, object]] = []
    backstage = [text.strip() for text in draft.backstage if text.strip()]
    dropped: dict[str, int] = {}

    def drop(reason: str) -> None:
        dropped[reason] = dropped.get(reason, 0) + 1

    for item in draft.facts[:MAX_MATERIAL_FACTS]:
        source = by_id.get(item.evidence_id)
        statement = item.statement.strip()
        quote = item.quote.strip()
        if source is None:
            drop("unknown_evidence")
        elif not statement or not quote[:300]:
            drop("empty")
        elif _CATALOGUE_TRIVIA.search(statement) or _CATALOGUE_TRIVIA.search(quote):
            backstage.append(statement[:300])
            drop("backstage")
        elif has_relative_time(statement):
            drop("relative_time")
        elif not quote_in_source(quote, source.claim_or_excerpt):
            drop("quote_not_in_evidence")
        elif qualifiers_missing(statement, quote):
            drop("qualifier_not_in_quote")
        elif (roles := roles_in(statement)) and not quote_backs_roles(quote, roles):
            drop("role_not_in_quote")
        elif (
            item.scope == "recording"
            and source.track_refs
            and recording_refs
            and not set(source.track_refs) & set(recording_refs)
        ):
            drop("other_recording")
        else:
            version = item.version_scope.strip() if item.version_scope else None
            if item.scope == "recording" and source.track_refs and recording_refs:
                version = next(ref for ref in recording_refs if ref in source.track_refs)
            facts.append(
                {
                    "statement": statement[:400],
                    "evidence_id": source.id,
                    "quote": quote[:300],
                    "scope": StoryScope(item.scope),
                    "subject": (item.subject.strip() or draft.subject.strip())[:120],
                    "version_scope": version[:200] if version else None,
                }
            )
    if dropped:
        logger.info("story_material_dropped %s", ",".join(f"{k}={v}" for k, v in sorted(dropped.items())))
    if len(facts) < MIN_VERIFIED_FACTS or not draft.central_question.strip():
        return None
    numbered = [{"fact_id": f"{story_id}-F{n}", **fact} for n, fact in enumerate(facts, 1)]
    return StoryMaterial.model_validate(
        {
            "story_id": story_id,
            "subject": draft.subject.strip()[:120] or "story",
            "scope": StoryScope(draft.scope),
            "recording_refs": list(recording_refs)[:4],
            "central_question": draft.central_question.strip()[:200],
            "facts": numbered,
            "editorial_angle": (draft.editorial_angle or "").strip()[:300] or None,
            "do_not_infer": [t.strip()[:300] for t in draft.do_not_infer if t.strip()][:6],
            "backstage": [t[:300] for t in backstage][:6],
        }
    )
