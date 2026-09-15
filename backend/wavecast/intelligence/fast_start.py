"""Latency-critical first-script planning and deterministic fallback."""

from __future__ import annotations

import asyncio
from time import perf_counter

from wavecast.providers.contracts import ProgressiveLLMProvider
from wavecast.providers.profiles import InferenceProfile, StructuredTransport

from .models import (
    FastResearchInput,
    FastResearchResult,
    FastStartPlan,
    NarrationScript,
    ResearchBundle,
    TasteHypothesis,
)
from .research import FastResearchService
from .trace import GenerationTrace

FastStructuredProvider = ProgressiveLLMProvider


class FastStartPlanner:
    def __init__(self, llm: FastStructuredProvider) -> None:
        self.llm = llm

    async def plan(
        self,
        request: FastResearchInput,
        research: FastResearchResult,
        *,
        trace: GenerationTrace | None = None,
    ) -> FastStartPlan:
        prompt = self._prompt(request, research)
        try:
            plan = await self.llm.structured(
                prompt,
                FastStartPlan,
                transport=StructuredTransport.RESPONSES_JSON_SCHEMA,
                profile=InferenceProfile.FAST,
                stage="fast_start",
            )
            if not isinstance(plan, FastStartPlan):
                raise TypeError("fast planner returned an unexpected output model")
            if trace:
                trace.mark(
                    "first_script_ready",
                    fallback=False,
                    candidate_count=len(plan.next_candidates),
                )
            return plan
        except Exception as error:
            if trace:
                trace.mark("fallback_used", reason=type(error).__name__)
            plan = deterministic_fallback(request, research)
            if trace:
                trace.mark(
                    "first_script_ready",
                    fallback=True,
                    candidate_count=len(plan.next_candidates),
                )
            return plan

    @staticmethod
    def _prompt(request: FastResearchInput, research: FastResearchResult) -> str:
        return (
            "Create one FastStartPlan for a guided-listening episode. Use only the normalized "
            "evidence below. Separate evidence, hypotheses, and uncertainty. Prefer groove, "
            "harmony, production texture, instrumentation, vocal style, rhythmic feel, era, "
            "scene, and emotional energy over generic genre tags. Choose a small immediate "
            "direction and write one spoken first narration; never invent unsupported facts.\n"
            f"Request: {request.model_dump_json()}\n"
            f"Research: {research.bundle.model_dump_json()}"
        )


def deterministic_fallback(
    request: FastResearchInput, research: FastResearchResult
) -> FastStartPlan:
    anchor = request.anchor_tracks[0] if request.anchor_tracks else request.topic
    return FastStartPlan(
        anchor_understanding=[f"Continue from the known anchor: {anchor}"],
        immediate_taste_hypotheses=[
            TasteHypothesis(
                dimension="listening direction",
                interpretation="Follow rhythm, texture, and atmosphere before adding stronger novelty.",
                confidence=0.4,
            )
        ],
        next_candidates=research.bundle.candidates[:3],
        selected_next_track=None,
        first_narration=NarrationScript(
            text=(
                f"先从 {anchor} 开始。接下来我们先沿着节奏、质感和氛围往外走，"
                "再决定下一步要靠近，还是转向一个新的方向。"
            ),
            intended_duration_seconds=10,
        ),
        uncertainties=["Fast research or structured planning was unavailable; no factual claim was added."],
    )


class FastPathCoordinator:
    """Owns the total first-script deadline; intelligence never owns episode lifecycle."""

    def __init__(
        self,
        *,
        research: FastResearchService,
        planner: FastStartPlanner,
        deadline_seconds: float = 15.0,
    ) -> None:
        self.research = research
        self.planner = planner
        self.deadline_seconds = deadline_seconds

    async def run(self, request: FastResearchInput, *, request_id: str) -> FastPathResult:
        trace = GenerationTrace(request_id=request_id)
        started = perf_counter()
        try:
            result = await asyncio.wait_for(
                self._run(request, trace=trace), timeout=self.deadline_seconds
            )
            return result
        except TimeoutError:
            research = FastResearchResult(
                bundle=research_anchor_bundle(request),
                elapsed_ms=int((perf_counter() - started) * 1000),
                queries=[],
            )
            trace.mark("fallback_used", reason="deadline")
            trace.mark("first_script_ready", fallback=True, candidate_count=0)
            return FastPathResult(
                research=research,
                plan=deterministic_fallback(request, research),
                trace=trace,
                elapsed_ms=int((perf_counter() - started) * 1000),
            )

    async def _run(
        self, request: FastResearchInput, *, trace: GenerationTrace
    ) -> FastPathResult:
        research = await self.research.run(request, trace=trace)
        plan = await self.planner.plan(request, research, trace=trace)
        return FastPathResult(
            research=research,
            plan=plan,
            trace=trace,
            elapsed_ms=trace.events[-1].elapsed_from_start_ms if trace.events else 0,
        )


class FastPathResult:
    def __init__(
        self,
        *,
        research: FastResearchResult,
        plan: FastStartPlan,
        trace: GenerationTrace,
        elapsed_ms: int,
    ) -> None:
        self.research = research
        self.plan = plan
        self.trace = trace
        self.elapsed_ms = elapsed_ms


def research_anchor_bundle(request: FastResearchInput) -> ResearchBundle:
    from .research import bundle_from_results

    return bundle_from_results(request, [], ["Fast path deadline exceeded; anchor-only context used."])
