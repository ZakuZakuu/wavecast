"""Cancellable background research, curation, and one future narration stage."""

from __future__ import annotations

import asyncio

from .curation import CuratorService
from .fast_start import FastPathResult
from .models import FastResearchInput, NarrationScript, ProgramSkeleton, ResearchBundle
from .planning import PlanningSession
from .research import BackgroundResearchService
from .trace import GenerationTrace
from .writer import WriterService


class BackgroundPipelineResult:
    def __init__(
        self,
        *,
        bundle: ResearchBundle,
        skeleton: ProgramSkeleton,
        future_script: NarrationScript | None,
        trace: GenerationTrace,
    ) -> None:
        self.bundle = bundle
        self.skeleton = skeleton
        self.future_script = future_script
        self.trace = trace


class BackgroundIntelligencePipeline:
    def __init__(
        self,
        *,
        research: BackgroundResearchService,
        curator: CuratorService,
        writer: WriterService,
    ) -> None:
        self.research = research
        self.curator = curator
        self.writer = writer

    async def run(
        self,
        request: FastResearchInput,
        fast_result: FastPathResult,
        *,
        cancel_event: asyncio.Event,
        trace: GenerationTrace,
        planning: PlanningSession | None = None,
    ) -> BackgroundPipelineResult | None:
        if cancel_event.is_set():
            return None
        trace.mark("background_research_started")
        bundle = await self.research.run(
            request, fast_result.research, cancel_event=cancel_event, trace=trace
        )
        if bundle is None or cancel_event.is_set():
            return None
        trace.mark("curator_started")
        skeleton = await self.curator.curate(
            bundle,
            fast_result.plan,
            desired_duration_seconds=request.desired_duration_seconds,
            committed_chapters=planning.committed_chapters if planning else [],
        )
        if cancel_event.is_set():
            return None
        if planning:
            planning.apply_skeleton(skeleton)
        future_script: NarrationScript | None = None
        if skeleton.chapters:
            trace.mark("writer_started")
            future_script = await self.writer.write(
                skeleton.chapters[0], bundle.evidence, previous_committed_context=""
            )
            trace.mark("chapter_script_ready", chapter_index=skeleton.chapters[0].index)
        trace.mark("program_skeleton_ready", chapter_count=len(skeleton.chapters))
        return BackgroundPipelineResult(
            bundle=bundle, skeleton=skeleton, future_script=future_script, trace=trace
        )
