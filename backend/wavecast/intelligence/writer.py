"""Tool-free narration writer over a scoped evidence set."""

from __future__ import annotations

from wavecast.providers.profiles import InferenceProfile, StructuredTransport

from .fast_start import FastStructuredProvider
from .models import (
    ChapterPlan,
    Evidence,
    NarrationScript,
    OutputLanguage,
    RadioScript,
    resolve_output_language,
)


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
        target_duration_seconds: int | None = None,
        output_language: OutputLanguage = OutputLanguage.AUTO,
        topic: str = "",
    ) -> RadioScript | NarrationScript:
        scoped = [item for item in evidence if item.id in set(chapter.evidence_ids)]
        selected_language = resolve_output_language(output_language, topic or chapter.reason)
        prompt = (
            "Write a structured radio script for this chapter, not an article. Use only the "
            "scoped evidence; keep factual claims separately identified by evidence IDs, avoid "
            "citation language in spoken text, and do not browse or change the selected track. "
            "Return ordered blocks using only intro, track_intro, transition, or outro. Each "
            "block must be speakable and independently timed. The chapter is a "
            "narrative beat and may have no playable track; do not invent or substitute a song. "
            "Aim for the allocated narration duration rather than a generic short answer. "
            "Keep `text` as the listener-visible copy and optionally provide `tts_text` when "
            "spoken pronunciation should differ. For example, display `3rd Coast` but use "
            "`Third Coast` for TTS. Do not use broad regex or dictionary substitutions. "
            f"Write in output language {selected_language.value}.\n"
            f"Chapter: {chapter.model_dump_json()}\n"
            f"Evidence: {[item.model_dump() for item in scoped]}\n"
            f"Previous context: {previous_committed_context[:1000]}\n"
            f"Next track metadata: {next_track_metadata[:500]}\n"
            f"Host style: {host_style}\n"
            f"Target narration duration seconds: {target_duration_seconds or 'use chapter context'}"
        )
        result = await self.llm.structured(
            prompt,
            RadioScript,
            transport=StructuredTransport.RESPONSES_JSON_SCHEMA,
            profile=InferenceProfile.BALANCED,
            stage="writer",
        )
        if not isinstance(result, (RadioScript, NarrationScript)):
            raise TypeError("writer returned an unexpected output model")
        return result
