"""Deterministic bounded search stages for progressive intelligence."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from hashlib import sha1
from time import perf_counter
from typing import Protocol, cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from wavecast.providers.contracts import ProgressiveLLMProvider, SearchResult
from wavecast.providers.errors import ProviderInvalidResponseError
from wavecast.providers.profiles import InferenceProfile, StructuredTransport
from wavecast.providers.usage import UsageLedger

from .models import (
    Evidence,
    EvidenceSourceCategory,
    FastResearchInput,
    FastResearchResult,
    FastStartPlan,
    PlannedResearchQuery,
    ResearchBundle,
    ResearchFacet,
    ResearchPlan,
    ResearchPlanMode,
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


class ResearchIntentPlanner(Protocol):
    async def plan(
        self,
        request: FastResearchInput,
        fast_result: FastResultLike,
        *,
        trace: GenerationTrace | None = None,
    ) -> ResearchPlan: ...


FAST_RESEARCH_DEADLINE_SECONDS = 4.5
BACKGROUND_RESEARCH_DEADLINE_SECONDS = 8.0
BACKGROUND_RESEARCH_PLANNER_DEADLINE_SECONDS = 20.0


class BackgroundResearchPlanner:
    """One bounded, provider-neutral planning call for slow research."""

    def __init__(self, llm: ProgressiveLLMProvider) -> None:
        self.llm = llm

    async def plan(
        self,
        request: FastResearchInput,
        fast_result: FastResultLike,
        *,
        trace: GenerationTrace | None = None,
    ) -> ResearchPlan:
        result = await self.llm.structured(
            self._prompt(request, fast_result),
            ResearchPlan,
            transport=StructuredTransport.RESPONSES_JSON_SCHEMA,
            profile=InferenceProfile.BALANCED,
            stage="research_planner",
        )
        if not isinstance(result, ResearchPlan):
            raise TypeError("background research planner returned an unexpected output model")
        normalized = normalize_research_plan(result)
        validate_background_research_plan(normalized)
        if trace:
            trace.mark(
                "background_research_plan_regenerated",
                plan_source="background_planner",
                research_facet_count=len(normalized.facets),
                planned_background_query_count=len(normalized.background_queries),
            )
        return normalized

    @staticmethod
    def _prompt(request: FastResearchInput, fast_result: FastResultLike) -> str:
        return (
            "Plan the bounded background research for the listener's actual topic. This is a "
            "research-intent step, not a fixed show-type classifier and not a search call. "
            "Adapt the facets to the request: artist/career history, music discovery, "
            "creative-work analysis, and non-music context should produce different questions "
            "when warranted. Use normalized fast evidence as context, but do not invent facts "
            "or track entities. Propose zero to eight distinct queries; application code will "
            "execute at most one DISCOVERY query through Exa and two RESEARCH/EXACT queries "
            "through Tavily. Every query needs a non-empty rationale and valid facet IDs. "
            "Use research_mode=adaptive when more evidence is useful; if no additional "
            "background research is needed, set research_mode=no_additional_research and give "
            "a concrete no_research_reason. An adaptive plan with no facets or queries is "
            "incomplete and must not be used to skip planning. "
            "Keep source_preferences as preferences, not authority claims. Keep concrete "
            "fact, correlation, causal claim, editorial interpretation, and uncertainty "
            "distinct so downstream Writer/Curator stages can preserve that boundary. When the "
            "topic requires a route between tracks, scenes, eras, or an artist lineage, prefer "
            "an open-ended relation, scene, or lineage facet that can explain why two musical "
            "steps connect. Do not add a query budget or force a relationship when the evidence "
            "does not support one."
            f"\nRequest: {request.model_dump_json()}"
            f"\nFast evidence: {fast_result.bundle.model_dump_json()}"
            f"\nFast plan context: {fast_result.plan.model_dump_json()}"
        )


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
        planner_deadline_seconds: float = BACKGROUND_RESEARCH_PLANNER_DEADLINE_SECONDS,
        planner: ResearchIntentPlanner | None = None,
    ) -> None:
        self.discovery = discovery
        self.research = research
        self.ledger = ledger
        self.deadline_seconds = deadline_seconds
        self.planner_deadline_seconds = planner_deadline_seconds
        self.planner = planner

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
        try:
            plan = await self._plan_for(
                request, fast_result, cancel_event=cancel_event, trace=trace
            )
        except asyncio.CancelledError:
            if cancel_event is not None and cancel_event.is_set():
                return None
            raise
        selected = select_background_queries(plan, fast_result.queries)
        if trace:
            trace.mark(
                "background_started",
                query_count=len(selected),
                research_facet_count=len(plan.facets),
                planned_background_query_count=len(plan.background_queries),
                selected_queries=[
                    {
                        "provider": provider,
                        "query": planned.query,
                        "intent": planned.intent.value,
                        "facet_ids": list(planned.facet_ids),
                    }
                    for provider, planned in selected
                ],
            )
        tasks: dict[asyncio.Task[list[SearchResult]], tuple[str, PlannedResearchQuery]] = {}
        for provider, query in selected:
            search = self.discovery if provider == "exa" else self.research
            tasks[asyncio.create_task(search.search(query.query, limit=4, stage="background_research"))] = (
                provider,
                query,
            )
        if not tasks:
            merged = merge_bundles(
                fast_result.bundle,
                bundle_from_results(
                    request, [], [], query_context={}, research_plan=plan
                ),
            )
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
                research_plan=plan,
            ),
        )
        if trace:
            trace.mark("background_research_done", evidence_count=len(merged.evidence))
        return merged

    async def _plan_for(
        self,
        request: FastResearchInput,
        fast_result: FastResearchResult | FastResultLike,
        *,
        cancel_event: asyncio.Event | None,
        trace: GenerationTrace | None,
    ) -> ResearchPlan:
        candidate = getattr(fast_result, "plan", None)
        trace_fallback = bool(
            getattr(getattr(fast_result, "trace", None), "fallback_used", False)
        )
        if (
            isinstance(candidate, FastStartPlan)
            and not trace_fallback
            and candidate.research_plan.research_mode is ResearchPlanMode.ADAPTIVE
            and not candidate._research_plan_omitted
            and not _is_generic_or_empty_plan(request, candidate.research_plan)
        ):
            if trace:
                trace.mark(
                    "background_research_plan_used",
                    plan_source="fast_start",
                    research_facet_count=len(candidate.research_plan.facets),
                    planned_background_query_count=len(candidate.research_plan.background_queries),
                )
            return normalize_research_plan(candidate.research_plan)

        if (
            isinstance(candidate, FastStartPlan)
            and not trace_fallback
            and candidate.research_plan.research_mode
            is ResearchPlanMode.NO_ADDITIONAL_RESEARCH
        ):
            if trace:
                trace.mark(
                    "background_research_plan_used",
                    plan_source="fast_start_no_additional_research",
                    research_facet_count=len(candidate.research_plan.facets),
                    planned_background_query_count=0,
                )
            return candidate.research_plan

        if cancel_event and cancel_event.is_set():
            return generic_research_plan(request)
        if self.planner is not None and isinstance(candidate, FastStartPlan):
            try:
                return await self._run_planner(
                    request,
                    cast(FastResultLike, fast_result),
                    cancel_event=cancel_event,
                    trace=trace,
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                if trace:
                    trace.mark(
                        "background_research_plan_fallback",
                        plan_source="generic_fallback",
                        reason=type(error).__name__,
                    )
        fallback = generic_research_plan(request)
        if trace and not any(
            event.name == "background_research_plan_fallback" for event in trace.events
        ):
            trace.mark(
                "background_research_plan_fallback",
                plan_source="generic_fallback",
                reason="planner_unavailable",
            )
        return fallback

    async def _run_planner(
        self,
        request: FastResearchInput,
        fast_result: FastResultLike,
        *,
        cancel_event: asyncio.Event | None,
        trace: GenerationTrace | None,
    ) -> ResearchPlan:
        """Run the planner with its own bounded deadline, separate from search."""

        assert self.planner is not None
        planner_task = asyncio.create_task(
            self.planner.plan(request, fast_result, trace=trace)
        )
        cancel_task: asyncio.Task[bool] | None = None
        waitables: set[asyncio.Task[ResearchPlan] | asyncio.Task[bool]] = {planner_task}
        if cancel_event is not None:
            cancel_task = asyncio.create_task(cancel_event.wait())
            waitables.add(cancel_task)
        done, pending = await asyncio.wait(waitables, timeout=self.planner_deadline_seconds)
        if cancel_task is not None and cancel_task in done and cancel_event is not None:
            planner_task.cancel()
            await asyncio.gather(planner_task, return_exceptions=True)
            raise asyncio.CancelledError
        if planner_task not in done:
            planner_task.cancel()
            await asyncio.gather(planner_task, return_exceptions=True)
            raise TimeoutError
        for task in pending:
            task.cancel()
        if cancel_task is not None:
            await asyncio.gather(cancel_task, return_exceptions=True)
        return planner_task.result()


def _is_generic_or_empty_plan(request: FastResearchInput, plan: ResearchPlan) -> bool:
    """Identify plans that lack enough intent for independent background work."""

    return not is_effective_research_plan(plan) or plan == generic_research_plan(request)


def is_effective_research_plan(plan: ResearchPlan) -> bool:
    """Return whether a plan has an explicit, executable research decision."""

    if plan.research_mode is ResearchPlanMode.NO_ADDITIONAL_RESEARCH:
        return bool(plan.no_research_reason) and not plan.background_queries
    return bool(plan.facets and plan.background_queries)


def validate_background_research_plan(plan: ResearchPlan) -> ResearchPlan:
    """Reject planner output that would silently turn adaptive research off."""

    if not is_effective_research_plan(plan):
        raise ProviderInvalidResponseError(
            "background research planner returned an effectively empty adaptive plan"
        )
    return plan


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


def normalize_research_plan(plan: ResearchPlan) -> ResearchPlan:
    """Normalize query whitespace and reject broken facet links deterministically."""

    facet_ids = {facet.id for facet in plan.facets}
    seen: set[str] = set()
    queries: list[PlannedResearchQuery] = []
    for planned in plan.background_queries:
        normalized_query = " ".join(planned.query.split())
        key = normalized_query.casefold()
        if not normalized_query or key in seen:
            continue
        unknown_facets = set(planned.facet_ids) - facet_ids
        if unknown_facets:
            raise ProviderInvalidResponseError("research plan referenced an unknown facet")
        seen.add(key)
        queries.append(
            planned.model_copy(
                update={
                    "query": normalized_query,
                    "facet_ids": list(dict.fromkeys(planned.facet_ids)),
                }
            )
        )
    return plan.model_copy(update={"background_queries": queries})


def canonicalize_url(url: str) -> str:
    """Canonicalize safe URL identity without guessing path equivalence."""

    raw = url.strip()
    parsed = urlsplit(raw)
    if not parsed.scheme or not parsed.netloc:
        return raw
    scheme = parsed.scheme.casefold()
    hostname = (parsed.hostname or "").casefold()
    if not hostname:
        return raw
    try:
        port = parsed.port
    except ValueError:
        return raw
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    netloc = hostname if port is None or default_port else f"{hostname}:{port}"
    path = parsed.path or "/"
    tracking_names = {"fbclid", "gclid", "mc_cid", "mc_eid"}
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_") and key.casefold() not in tracking_names
    ]
    query_pairs.sort()
    return urlunsplit((scheme, netloc, path, urlencode(query_pairs, doseq=True), ""))


def _source_metadata(url: str) -> tuple[str, EvidenceSourceCategory]:
    parsed = urlsplit(url)
    domain = (parsed.hostname or "").casefold()
    base_domain = domain.removeprefix("www.")
    if base_domain in {"wikipedia.org", "wikidata.org"} or base_domain.endswith(".wikipedia.org"):
        category = EvidenceSourceCategory.REFERENCE
    elif base_domain in {"youtube.com", "youtu.be", "vimeo.com"}:
        category = EvidenceSourceCategory.VIDEO
    elif base_domain in {"reddit.com", "news.ycombinator.com"} or base_domain.endswith(".reddit.com"):
        category = EvidenceSourceCategory.COMMUNITY
    elif base_domain in {
        "apnews.com",
        "bbc.com",
        "bbc.co.uk",
        "theguardian.com",
        "nytimes.com",
        "reuters.com",
        "rollingstone.com",
        "pitchfork.com",
    }:
        category = EvidenceSourceCategory.NEWS
    elif base_domain.endswith(".gov") or base_domain.endswith(".edu"):
        category = EvidenceSourceCategory.INSTITUTIONAL
    elif base_domain in {"musicbrainz.org", "discogs.com"}:
        category = EvidenceSourceCategory.CATALOG
    else:
        category = EvidenceSourceCategory.UNKNOWN
    return domain, category


def _preference_rank(
    category: EvidenceSourceCategory,
    preferences: list[str],
) -> int | None:
    if not preferences:
        return None
    for index, preference in enumerate(preferences):
        token = preference.casefold().strip()
        # Only exact taxonomy names are deterministic enough to influence
        # ordering.  Tokens such as ``primary``, ``official``, and
        # ``interview`` require source-specific semantics that this layer does
        # not possess, so they remain unresolved rather than implying authority.
        if category.value == token:
            return index
    return len(preferences)


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
        canonical_url = canonicalize_url(result.url)
        key = canonical_url or f"{result.provider}:{result.title.casefold()}:{result.query.casefold()}"
        if key in seen:
            continue
        seen.add(key)
        normalized.append(
            result.model_copy(
                update={
                    "url": canonical_url,
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
    research_plan: ResearchPlan | None = None,
) -> ResearchBundle:
    evidence: list[Evidence] = []
    facets = {facet.id: facet for facet in (research_plan.facets if research_plan else [])}
    ranked_results: list[tuple[int, int | None, SearchResult]] = []
    for position, result in enumerate(results):
        canonical_url = canonicalize_url(result.url)
        planned = (query_context or {}).get(result.query)
        preferences = [
            preference
            for facet_id in (planned.facet_ids if planned else [])
            for preference in (
                facets[facet_id].source_preferences if facet_id in facets else []
            )
        ]
        _domain, category = _source_metadata(canonical_url)
        ranked_results.append((position, _preference_rank(category, preferences), result))
    if any(rank is not None for _, rank, _ in ranked_results):
        ranked_results.sort(key=lambda item: (item[1] if item[1] is not None else 10_000, item[0]))
    for _position, preference_rank, result in ranked_results:
        canonical_url = canonicalize_url(result.url)
        domain, category = _source_metadata(canonical_url)
        evidence_id = "evidence-" + sha1(
            (canonical_url or f"{result.provider}:{result.title.casefold()}:{result.query.casefold()}").encode()
        ).hexdigest()[:12]
        excerpt = result.content or result.snippet or result.title
        planned = (query_context or {}).get(result.query)
        evidence.append(
            Evidence(
                id=evidence_id,
                claim_or_excerpt=excerpt[:800],
                source_url=canonical_url,
                canonical_url=canonical_url,
                source_domain=domain,
                source_category=category,
                source_preference_rank=preference_rank,
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
        research_plan=research_plan,
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
            "research_plan": right.research_plan or left.research_plan,
            "uncertainties": [*left.uncertainties, *right.uncertainties],
        }
    )
