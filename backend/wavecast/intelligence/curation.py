"""Typed curator: chooses a listening arc without any search dependency."""

from __future__ import annotations

from wavecast.providers.errors import ProviderInvalidResponseError
from wavecast.providers.profiles import InferenceProfile, StructuredTransport

from .fast_start import FastStructuredProvider
from .models import (
    ChapterPlan,
    FastStartPlan,
    OutputLanguage,
    ProgramSkeleton,
    ResearchBundle,
    resolve_output_language,
)


class CuratorService:
    def __init__(self, llm: FastStructuredProvider) -> None:
        self.llm = llm

    async def curate(
        self,
        bundle: ResearchBundle,
        fast_plan: FastStartPlan,
        *,
        desired_duration_seconds: int,
        committed_chapters: list[ChapterPlan] | None = None,
        output_language: OutputLanguage = OutputLanguage.AUTO,
        topic: str = "",
    ) -> ProgramSkeleton:
        committed = committed_chapters or []
        prompt = (
            "Sequence a deliberate chapter-ordered response to the listener's actual topic "
            "from normalized research, the FastStart plan, and the ResearchPlan. This may be a "
            "career, creative-work, analysis, history/context, or music-discovery request; "
            "adapt the editorial arc to the topic rather than assuming a similarity playlist. "
            "Playback order is exactly chapter order. Search is complete; do not request or "
            "invent web evidence. Each chapter is one narrative beat with zero or one supporting "
            "TrackProposal; do not add unrelated artists only to manufacture novelty. Keep a "
            "stable or repeated novelty distance when a meaningful move is not justified. "
            "A chapter is a narrative beat and may intentionally have no TrackProposal; do not "
            "invent a track to fill a story beat. "
            "novelty_distance may start at any supported "
            "distance; distances may be skipped, and repeated distances are allowed when "
            "intended. The sequence must never move backward: very_close <= close <= bridge "
            "<= discovery <= surprise. For example, [\"close\", \"bridge\", \"discovery\"] "
            "is valid, while [\"close\", \"surprise\", \"bridge\"] is invalid. Preserve "
            "committed chapters exactly and place speculative chapters after committed chapters. "
            "Define the distances semantically: very_close keeps the same core sonic identity; "
            "close introduces at least one new musical dimension; bridge connects anchor traits "
            "to a different artist, scene, or era; discovery leaves the immediate cluster while "
            "remaining strongly justified; surprise is less obvious but still coherent. Do not "
            "label a track discovery merely because it appears later. Unless the topic asks for "
            "a single-artist deep dive, later bridge/discovery chapters should introduce new "
            "artists or scenes only when they answer the topic. Use each chapter reason as a concise "
            "topic-specific rationale.\n"
            f"Research: {bundle.model_dump_json()}\n"
            f"Fast plan: {fast_plan.model_dump_json()}\n"
            f"Research plan: {fast_plan.research_plan.model_dump_json()}\n"
            f"Committed: {[item.model_dump() for item in committed]}\n"
            f"Duration: {desired_duration_seconds}\n"
            f"Output language: {resolve_output_language(output_language, topic).value}"
        )
        skeleton = await self.llm.structured(
            prompt,
            ProgramSkeleton,
            transport=StructuredTransport.RESPONSES_JSON_SCHEMA,
            profile=InferenceProfile.DEEP,
            stage="curator",
        )
        if not isinstance(skeleton, ProgramSkeleton):
            raise TypeError("curator returned an unexpected output model")
        return ensure_distance_curve(skeleton)


def ensure_distance_curve(skeleton: ProgramSkeleton) -> ProgramSkeleton:
    order = {
        "very_close": 1,
        "close": 2,
        "bridge": 3,
        "discovery": 4,
        "surprise": 5,
    }
    distances = [
        order[chapter.novelty_distance.value]
        for chapter in skeleton.chapters
        if chapter.novelty_distance is not None
    ]
    if distances != sorted(distances):
        values = [
            chapter.novelty_distance.value
            for chapter in skeleton.chapters
            if chapter.novelty_distance is not None
        ]
        raise ProviderInvalidResponseError(f"invalid novelty curve values: {values!r}")
    # Curator order and chapter indices are part of the narrative contract.  Do not
    # sort or renumber here: committed-prefix validation relies on exact identity.
    return skeleton
