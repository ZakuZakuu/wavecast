"""Typed curator: chooses a listening arc without any search dependency."""

from __future__ import annotations

from wavecast.providers.profiles import InferenceProfile, StructuredTransport

from .fast_start import FastStructuredProvider
from .models import ChapterPlan, FastStartPlan, ProgramSkeleton, ResearchBundle


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
    ) -> ProgramSkeleton:
        committed = committed_chapters or []
        prompt = (
            "Sequence a deliberate guided-listening arc from the normalized research and "
            "fast start. Search is complete; do not request or invent web evidence. Use the "
            "distance curve anchor, very_close, close, bridge, discovery, surprise, resolution "
            "where candidates support it. Preserve committed chapters conceptually.\n"
            f"Research: {bundle.model_dump_json()}\n"
            f"Fast plan: {fast_plan.model_dump_json()}\n"
            f"Committed: {[item.model_dump() for item in committed]}\n"
            f"Duration: {desired_duration_seconds}"
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
        "resolution": 6,
    }
    chapters = sorted(
        skeleton.chapters,
        key=lambda chapter: (order.get(chapter.novelty_distance.value, 99), chapter.index),
    )
    renumbered = [chapter.model_copy(update={"index": index}) for index, chapter in enumerate(chapters)]
    return skeleton.model_copy(update={"chapters": renumbered})
