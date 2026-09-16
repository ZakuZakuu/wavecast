"""Deterministic bounded search stages for progressive intelligence."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from hashlib import sha1
from time import perf_counter
from typing import Protocol

from wavecast.providers.contracts import SearchResult
from wavecast.providers.usage import UsageLedger

from .models import (
    Evidence,
    FastResearchInput,
    FastResearchResult,
    FastStartPlan,
    PlannedResearchQuery,
    ResearchBundle,
    ResearchFacet,
    ResearchPlan,
    SearchIntent,
    TrackProposal,
)
from .trace import GenerationTrace


class SearchCallable(Protocol):
    async def search(
        self, query: str, *, limit: int = 5, stage: str | None = None
    ) -> list[SearchResult]: ...


class FastResultLike(Protocol):
    """Shared view used by fast and background stages for normalized evidence."""

    @property
    def bundle(self) -> ResearchBundle: ...

    @property
    def queries(self) -> list[str]: ...

    @property
    def plan(self) -> FastStartPlan: ...


FAST_RESEARCH_DEADLINE_SECONDS = 4.5
BACKGROUND_RESEARCH_DEADLINE_SECONDS = 8.0


class FastResearchService:
    """Runs one Exa and one Tavily query concurrently; failures become uncertainty."""

    def __init__(
        self,
        *,
        discovery: SearchCallable,
        research: SearchCallable,
        ledger: UsageLedger | None = None,
        deadline_seconds: float = FAST_RESEARCH_DEADLINE_SECONDS,
    ) -> None:
        self.discovery = discovery
        self.research = research
        self.ledger = ledger
        self.deadline_seconds = deadline_seconds

    async def run(
        self, request: FastResearchInput, *, trace: GenerationTrace | None = None
    ) -> FastResearchResult:
        started = perf_counter()
        discovery_query, research_query = build_fast_queries(request)
        queries = [discovery_query, research_query]
        if trace:
            trace.mark("fast_research_started", query_count=len(queries))
        tasks = {
            asyncio.create_task(
                self.discovery.search(discovery_query, limit=4, stage="fast_research")
            ): "exa",
            asyncio.create_task(
                self.research.search(research_query, limit=4, stage="fast_research")
            ): "tavily",
        }
        results_by_provider: dict[str, list[SearchResult]] = {}
        failures: list[str] = []
        done, pending = await asyncio.wait(tasks, timeout=self.deadline_seconds)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            provider = tasks[task]
            try:
                results_by_provider[provider] = task.result()
                if trace:
                    trace.mark(f"{provider}_done", result_count=len(results_by_provider[provider]))
            except Exception as error:  # provider failures are data-quality uncertainty
                failures.append(f"{provider} unavailable: {type(error).__name__}")
                if trace:
                    trace.mark(f"{provider}_failed")
        for provider in tasks.values():
            if provider not in results_by_provider and provider not in {item.split()[0] for item in failures}:
                failures.append(f"{provider} unavailable: deadline")
        normalized = normalize_results(
            results_by_provider.get("exa", []) + results_by_provider.get("tavily", [])
        )
        fast_query_context = {
            discovery_query: PlannedResearchQuery(
                query=discovery_query,
                intent=SearchIntent.DISCOVERY,
                rationale="bounded fast context search",
            ),
            research_query: PlannedResearchQuery(
                query=research_query,
                intent=SearchIntent.RESEARCH,
                rationale="bounded fast evidence search",
            ),
        }
        bundle = bundle_from_results(
            request, normalized, failures, query_context=fast_query_context
        )
        elapsed_ms = int((perf_counter() - started) * 1000)
        if trace:
            trace.mark(
                "fast_research_done",
                evidence_count=len(bundle.evidence),
                elapsed_ms=elapsed_ms,
            )
        return FastResearchResult(bundle=bundle, elapsed_ms=elapsed_ms, queries=queries)


class BackgroundResearchService:
    """Adds bounded context after the fast path and can be cancelled before paid work."""

    def __init__(
        self,
        *,
        discovery: SearchCallable,
        research: SearchCallable,
        ledger: UsageLedger | None = None,
        deadline_seconds: float = BACKGROUND_RESEARCH_DEADLINE_SECONDS,
    ) -> None:
        self.discovery = discovery
        self.research = research
        self.ledger = ledger
        self.deadline_seconds = deadline_seconds

    async def run(
        self,
        request: FastResearchInput,
        fast_result: FastResearchResult | FastResultLike,
        *,
        cancel_event: asyncio.Event | None = None,
        trace: GenerationTrace | None = None,
    ) -> ResearchBundle | None:
        if cancel_event and cancel_event.is_set():
            return None
        plan = _research_plan_for(request, fast_result)
        selected = select_background_queries(plan, fast_result.queries)
        if trace:
            trace.mark(
                "background_started",
                query_count=len(selected),
                research_facet_count=len(plan.facets),
                planned_background_query_count=len(plan.background_queries),
            )
        tasks: dict[asyncio.Task[list[SearchResult]], tuple[str, PlannedResearchQuery]] = {}
        for provider, query in selected:
            search = self.discovery if provider == "exa" else self.research
            tasks[asyncio.create_task(search.search(query.query, limit=4, stage="background_research"))] = (
                provider,
                query,
            )
        if not tasks:
            merged = merge_bundles(fast_result.bundle, bundle_from_results(request, [], []))
            if trace:
                trace.mark("background_research_done", evidence_count=len(merged.evidence))
            return merged
        if cancel_event and cancel_event.is_set():
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            return None
        cancel_task: asyncio.Task[bool] | None = None
        waitables: set[
            asyncio.Task[list[SearchResult]] | asyncio.Task[bool]
        ] = set(tasks)
        if cancel_event:
            cancel_task = asyncio.create_task(cancel_event.wait())
            waitables.add(cancel_task)
        done, pending = await asyncio.wait(waitables, timeout=self.deadline_seconds)
        if cancel_task and cancel_task in done and cancel_event and cancel_event.is_set():
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            return None
        provider_pending = [provider_task for provider_task in tasks if provider_task in pending]
        pending_failures = [
            f"{tasks[provider_task][0]} unavailable: deadline"
            for provider_task in provider_pending
        ]
        for provider_task in provider_pending:
            provider_task.cancel()
        if provider_pending:
            await asyncio.gather(*provider_pending, return_exceptions=True)
        if cancel_task:
            cancel_task.cancel()
            await asyncio.gather(cancel_task, return_exceptions=True)
        extra: list[SearchResult] = []
        failures: list[str] = pending_failures
        query_context: dict[str, PlannedResearchQuery] = {}
        # Iterate in declared plan order rather than asyncio's unordered ``done`` set.
        # This keeps evidence and diagnostics deterministic while retaining concurrency.
        for task, (provider, planned_query) in tasks.items():
            if task not in done:
                continue
            query_context[planned_query.query] = planned_query
            try:
                extra.extend(task.result())
            except Exception as error:
                failures.append(f"{provider} unavailable: {type(error).__name__}")
                continue
        merged = merge_bundles(
            fast_result.bundle,
            bundle_from_results(
                request,
                normalize_results(extra),
                failures,
                query_context=query_context,
            ),
        )
        if trace:
            trace.mark("background_research_done", evidence_count=len(merged.evidence))
        return merged


def build_fast_queries(request: FastResearchInput) -> tuple[str, str]:
    anchors = ", ".join([*request.anchor_tracks, *request.anchor_artists])
    subject = " — ".join(part for part in (request.topic, anchors) if part)
    discovery = f"{subject}; relevant sources and related context"
    research = f"{subject}; background evidence and primary sources"
    return discovery, research


def build_background_queries(request: FastResearchInput) -> list[str]:
    """Compatibility view of the generic bounded fallback plan."""

    return [query.query for query in generic_research_plan(request).background_queries]


def generic_research_plan(request: FastResearchInput) -> ResearchPlan:
    """Build a topic-neutral plan when the structured fast planner is unavailable."""

    anchors = ", ".join([*request.anchor_tracks, *request.anchor_artists])
    subject = " — ".join(part for part in (request.topic, anchors) if part)
    return ResearchPlan(
        central_question=f"What reliable evidence best answers the listener's request about {request.topic}?",
        facets=[
            ResearchFacet(
                id="context",
                label="Context",
                question=f"What context helps explain the topic and its relevant examples: {request.topic}?",
                priority=80,
                source_preferences=["primary", "interview", "reference"],
            )
        ],
        background_queries=[
            PlannedResearchQuery(
                query=f"{subject}; related context and perspectives",
                intent=SearchIntent.DISCOVERY,
                facet_ids=["context"],
                rationale="find relevant context without assuming a show type",
            ),
            PlannedResearchQuery(
                query=f"{subject}; background evidence and primary sources",
                intent=SearchIntent.RESEARCH,
                facet_ids=["context"],
                rationale="ground the episode in reliable evidence",
            ),
            PlannedResearchQuery(
                query=f"{subject}; exact references and named entities",
                intent=SearchIntent.EXACT,
                facet_ids=["context"],
                rationale="verify concrete references when available",
            ),
        ],
    )


def _research_plan_for(
    request: FastResearchInput, fast_result: FastResearchResult | FastResultLike
) -> ResearchPlan:
    candidate = getattr(fast_result, "plan", None)
    if isinstance(candidate, FastStartPlan):
        return candidate.research_plan
    return generic_research_plan(request)


def select_background_queries(
    plan: ResearchPlan, fast_queries: list[str]
) -> list[tuple[str, PlannedResearchQuery]]:
    """Select at most one Exa and two Tavily queries in declared plan order."""

    fast_keys = {query.strip().casefold() for query in fast_queries}
    seen: set[str] = set()
    exa_count = 0
    tavily_count = 0
    selected: list[tuple[str, PlannedResearchQuery]] = []
    for query in plan.background_queries:
        key = query.query.strip().casefold()
        if not key or key in fast_keys or key in seen:
            continue
        seen.add(key)
        if query.intent is SearchIntent.DISCOVERY:
            if exa_count >= 1:
                continue
            exa_count += 1
            selected.append(("exa", query))
        else:
            if tavily_count >= 2:
                continue
            tavily_count += 1
            selected.append(("tavily", query))
        if len(selected) == 3:
            break
    return selected


def normalize_results(results: list[SearchResult]) -> list[SearchResult]:
    seen: set[str] = set()
    normalized: list[SearchResult] = []
    for result in results:
        key = result.url or f"{result.provider}:{result.title.lower()}"
        if key in seen:
            continue
        seen.add(key)
        normalized.append(
            result.model_copy(
                update={
                    "snippet": result.snippet[:600],
                    "content": (result.content or result.snippet)[:800],
                }
            )
        )
    return normalized


def bundle_from_results(
    request: FastResearchInput,
    results: list[SearchResult],
    uncertainties: list[str],
    *,
    query_context: Mapping[str, PlannedResearchQuery] | None = None,
) -> ResearchBundle:
    evidence: list[Evidence] = []
    for result in results:
        evidence_id = "evidence-" + sha1(
            f"{result.provider}|{result.url}|{result.query}".encode()
        ).hexdigest()[:12]
        excerpt = result.content or result.snippet or result.title
        planned = (query_context or {}).get(result.query)
        evidence.append(
            Evidence(
                id=evidence_id,
                claim_or_excerpt=excerpt[:800],
                source_url=result.url,
                source_provider=result.provider,
                confidence=result.score if result.score is not None else 0.5,
                query=result.query,
                source_title=result.title,
                facet_ids=list(planned.facet_ids) if planned else [],
                search_intent=planned.intent if planned else None,
            )
        )
    return ResearchBundle(
        anchors=[*request.anchor_tracks, *request.anchor_artists],
        taste_hypotheses=[],
        evidence=evidence,
        # A webpage title is evidence, not a recommendation.  Track candidates
        # require explicit provider entities or downstream curator inference.
        candidates=[],
        uncertainties=uncertainties,
    )


def merge_bundles(left: ResearchBundle, right: ResearchBundle) -> ResearchBundle:
    evidence_by_id = {item.id: item for item in [*left.evidence, *right.evidence]}
    candidate_keys: set[tuple[str, str]] = set()
    candidates: list[TrackProposal] = []
    for candidate in [*left.candidates, *right.candidates]:
        key = (candidate.artist.lower(), candidate.title.lower())
        if key not in candidate_keys:
            candidate_keys.add(key)
            candidates.append(candidate)
    return left.model_copy(
        update={
            "evidence": list(evidence_by_id.values()),
            "candidates": candidates,
            "uncertainties": [*left.uncertainties, *right.uncertainties],
        }
    )
