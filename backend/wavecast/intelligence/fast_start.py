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
    OutputLanguage,
    ResearchBundle,
    resolve_output_language,
)
from .research import FastResearchService, generic_research_plan
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
        if trace:
            trace.mark("fast_planner_started")
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
            if "research_plan" not in plan.model_fields_set:
                plan = plan.model_copy(update={"research_plan": generic_research_plan(request)})
            if trace:
                trace.mark(
                    "research_plan_ready",
                    research_facet_count=len(plan.research_plan.facets),
                    planned_background_query_count=len(plan.research_plan.background_queries),
                )
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
                    "research_plan_ready",
                    research_facet_count=len(plan.research_plan.facets),
                    planned_background_query_count=len(plan.research_plan.background_queries),
                )
                trace.mark(
                    "first_script_ready",
                    fallback=True,
                    candidate_count=len(plan.next_candidates),
                )
            return plan

    @staticmethod
    def _prompt(request: FastResearchInput, research: FastResearchResult) -> str:
        language = resolve_output_language(request.output_language, request.topic)
        return (
            "Create one FastStartPlan for this listener request. Use only normalized evidence "
            "below and keep evidence, hypotheses, and uncertainty separate. Do not assume the "
            "request is a music-discovery prompt: it may ask about a career, a creative work, "
            "analysis, history/context, or discovery. Interpret the actual topic and anchors. "
            "Taste hypotheses may be empty when the request does not support them. Choose a "
            "small immediate direction and write one spoken first narration without unsupported "
            "facts. Also produce a ResearchPlan: state the central question, define open-ended "
            "facets with stable IDs, and propose a small pool of zero to eight bounded background "
            "queries; application code will select at most three for execution. "
            "Each query must declare DISCOVERY, RESEARCH, or EXACT intent, facet IDs, and a "
            "short rationale. Search intent is operational routing, not a show-type classifier. "
            "Do not force similarity, novelty, genre, or sonic dimensions when the request does "
            "not ask for them. Preserve the requested output language; `auto` is inferred from "
            "the user's topic, not from artist or track names.\n"
            f"Output language: {language.value}\n"
            f"Request: {request.model_dump_json()}\n"
            f"Research: {research.bundle.model_dump_json()}"
        )


def deterministic_fallback(
    request: FastResearchInput, research: FastResearchResult
) -> FastStartPlan:
    anchor = request.anchor_tracks[0] if request.anchor_tracks else request.topic
    language = resolve_output_language(request.output_language, request.topic)
    if language is OutputLanguage.ZH_CN:
        narration = f"先从 {anchor} 开始。接下来我们会围绕这个请求整理可靠背景，再根据证据决定下一步。"
    elif language is OutputLanguage.JA_JP:
        narration = f"まず {anchor} から始めます。次に、利用できる根拠をもとに進む方向を決めます。"
    else:
        narration = (
            f"We will start with {anchor}, then use the available evidence to decide where to go next."
        )
    return FastStartPlan(
        anchor_understanding=[f"Continue from the known anchor: {anchor}"],
        immediate_taste_hypotheses=[],
        next_candidates=research.bundle.candidates[:3],
        selected_next_track=None,
        first_narration=NarrationScript(
            text=narration,
            intended_duration_seconds=10,
        ),
        uncertainties=["Fast research or structured planning was unavailable; no factual claim was added."],
        research_plan=generic_research_plan(request),
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
            if not any(
                event.name in {"fast_research_done", "fast_research_timed_out"}
                for event in trace.events
            ):
                trace.mark(
                    "fast_research_timed_out",
                    elapsed_ms=int((perf_counter() - started) * 1000),
                )
            research = FastResearchResult(
                bundle=research_anchor_bundle(request),
                elapsed_ms=int((perf_counter() - started) * 1000),
                queries=[],
            )
            trace.mark("fallback_used", reason="deadline")
            fallback_plan = deterministic_fallback(request, research)
            trace.mark(
                "research_plan_ready",
                research_facet_count=len(fallback_plan.research_plan.facets),
                planned_background_query_count=len(fallback_plan.research_plan.background_queries),
            )
            trace.mark("first_script_ready", fallback=True, candidate_count=0)
            return FastPathResult(
                research=research,
                plan=fallback_plan,
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

    @property
    def queries(self) -> list[str]:
        """Expose fast-stage queries to cancellable background deduplication."""
        return self.research.queries

    @property
    def bundle(self) -> ResearchBundle:
        """Expose normalized fast evidence to the background merge stage."""
        return self.research.bundle


def research_anchor_bundle(request: FastResearchInput) -> ResearchBundle:
    from .research import bundle_from_results

    return bundle_from_results(request, [], ["Fast path deadline exceeded; anchor-only context used."])
