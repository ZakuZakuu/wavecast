"""Tool-free narration writer over a scoped evidence set."""

from __future__ import annotations

from wavecast.providers.profiles import InferenceProfile, StructuredTransport

from .fast_start import FastStructuredProvider
from .models import ChapterPlan, Evidence, NarrationScript


class WriterService:
    def __init__(self, llm: FastStructuredProvider) -> None:
        self.llm = llm

    async def write(
        self,
        chapter: ChapterPlan,
        evidence: list[Evidence],
        *,
        previous_committed_context: str = "",
        next_track_metadata: str = "",
        host_style: str = "warm, concise, spoken",
    ) -> NarrationScript:
        scoped = [item for item in evidence if item.id in set(chapter.evidence_ids)]
        prompt = (
            "Write a short spoken transition for this chapter. Use only the scoped evidence; "
            "keep factual claims separately identified by evidence IDs, avoid citation language "
            "in the spoken text, and do not browse or change the selected track.\n"
            f"Chapter: {chapter.model_dump_json()}\n"
            f"Evidence: {[item.model_dump() for item in scoped]}\n"
            f"Previous context: {previous_committed_context[:1000]}\n"
            f"Next track metadata: {next_track_metadata[:500]}\n"
            f"Host style: {host_style}"
        )
        result = await self.llm.structured(
            prompt,
            NarrationScript,
            transport=StructuredTransport.RESPONSES_JSON_SCHEMA,
            profile=InferenceProfile.BALANCED,
            stage="writer",
        )
        if not isinstance(result, NarrationScript):
            raise TypeError("writer returned an unexpected output model")
        return result
