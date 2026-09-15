"""Deterministic bounded search stages for progressive intelligence."""

from __future__ import annotations

import asyncio
from hashlib import sha1
from time import perf_counter
from typing import Protocol

from wavecast.providers.contracts import SearchResult
from wavecast.providers.usage import UsageLedger

from .models import (
    Evidence,
    FastResearchInput,
    FastResearchResult,
    ResearchBundle,
    TrackCandidate,
)
from .trace import GenerationTrace


class SearchCallable(Protocol):
    async def search(
        self, query: str, *, limit: int = 5, stage: str | None = None
    ) -> list[SearchResult]: ...


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
        bundle = bundle_from_results(request, normalized, failures)
        elapsed_ms = int((perf_counter() - started) * 1000)
        if trace:
            trace.mark("fast_research_done", evidence_count=len(bundle.evidence))
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
        fast_result: FastResearchResult,
        *,
        cancel_event: asyncio.Event | None = None,
        trace: GenerationTrace | None = None,
    ) -> ResearchBundle | None:
        if cancel_event and cancel_event.is_set():
            return None
        queries = build_background_queries(request)
        queries = [query for query in queries if query not in set(fast_result.queries)]
        if trace:
            trace.mark("background_started", query_count=len(queries))
        tasks = {
            asyncio.create_task(
                self.discovery.search(queries[0], limit=4, stage="background_research")
            ): "exa",
            asyncio.create_task(
                self.research.search(queries[1], limit=4, stage="background_research")
            ): "tavily",
            asyncio.create_task(
                self.research.search(queries[2], limit=4, stage="background_research")
            ): "tavily",
        }
        if cancel_event and cancel_event.is_set():
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            return None
        done, pending = await asyncio.wait(tasks, timeout=self.deadline_seconds)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        extra: list[SearchResult] = []
        for task in done:
            try:
                extra.extend(task.result())
            except Exception:
                continue
        merged = merge_bundles(fast_result.bundle, bundle_from_results(request, normalize_results(extra), []))
        if trace:
            trace.mark("background_research_done", evidence_count=len(merged.evidence))
        return merged


def build_fast_queries(request: FastResearchInput) -> tuple[str, str]:
    anchors = ", ".join([*request.anchor_tracks, *request.anchor_artists]) or request.topic
    discovery = (
        f"{anchors}; music discovery by groove harmony production texture instrumentation "
        "vocal style rhythmic feel era scene"
    )
    research = f"{request.topic} {anchors} musical context style evidence"
    return discovery, research


def build_background_queries(request: FastResearchInput) -> list[str]:
    anchors = ", ".join([*request.anchor_tracks, *request.anchor_artists]) or request.topic
    return [
        f"{anchors} adjacent artists scenes and production lineage",
        f"{request.topic} historical context and documented influences",
        f"{anchors} groove harmony instrumentation and emotional energy",
    ]


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
    request: FastResearchInput, results: list[SearchResult], uncertainties: list[str]
) -> ResearchBundle:
    evidence: list[Evidence] = []
    for result in results:
        evidence_id = "evidence-" + sha1(
            f"{result.provider}|{result.url}|{result.query}".encode()
        ).hexdigest()[:12]
        excerpt = result.content or result.snippet or result.title
        evidence.append(
            Evidence(
                id=evidence_id,
                claim_or_excerpt=excerpt[:800],
                source_url=result.url,
                source_provider=result.provider,
                confidence=result.score if result.score is not None else 0.5,
                query=result.query,
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
    candidates: list[TrackCandidate] = []
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
