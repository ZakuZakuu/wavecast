"""Stations whose host talks a lot are researched more deeply than a casual one."""

import asyncio

from wavecast.assembly import LiveEpisodeAssemblyRequest, _research_depth
from wavecast.intelligence.models import (
    FastResearchInput,
    PlannedResearchQuery,
    ResearchDepth,
    ResearchFacet,
    ResearchPlan,
    SearchIntent,
)
from wavecast.intelligence.research import (
    BackgroundResearchPlanner,
    BackgroundResearchService,
    select_background_queries,
)
from wavecast.providers.contracts import SearchResult
from wavecast.stations import StationId

from tests.test_research_quality import PlannerFixture, _fallback_fast


def _big_plan() -> ResearchPlan:
    facets = [
        ResearchFacet(id=f"f{n}", label=f"Facet {n}", question="?", priority=90 - n, source_preferences=[])
        for n in range(8)
    ]
    queries = [
        PlannedResearchQuery(
            query=f"query {n}",
            intent=SearchIntent.DISCOVERY if n in (0, 3) else SearchIntent.RESEARCH,
            facet_ids=[f"f{n}"],
            rationale="fixture",
        )
        for n in range(8)
    ]
    return ResearchPlan(central_question="?", facets=facets, background_queries=queries)


def test_a_standard_budget_is_one_exa_and_two_tavily_queries() -> None:
    selected = select_background_queries(_big_plan(), [])

    assert [provider for provider, _query in selected] == ["exa", "tavily", "tavily"]


def test_a_deep_budget_is_two_exa_and_five_tavily_queries() -> None:
    selected = select_background_queries(_big_plan(), [], max_exa=2, max_tavily=5)

    providers = [provider for provider, _query in selected]
    assert providers.count("exa") == 2 and providers.count("tavily") == 5


def test_only_portraits_and_lineages_are_researched_deeply() -> None:
    def depth(station: StationId | None) -> ResearchDepth:
        return _research_depth(
            LiveEpisodeAssemblyRequest(topic="x", desired_duration_seconds=1200, station=station)
        )

    assert depth(StationId.PORTRAIT) is ResearchDepth.DEEP
    assert depth(StationId.LINEAGE) is ResearchDepth.DEEP
    for station in (None, StationId.CASUAL, StationId.CRATE, StationId.NIGHT):
        assert depth(station) is ResearchDepth.STANDARD


class _Search:
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[tuple[str, int]] = []

    async def search(self, query: str, *, limit: int = 5, stage: str | None = None) -> list[SearchResult]:
        del stage
        self.calls.append((query, limit))
        return []


def _run(depth: ResearchDepth) -> dict[str, list[tuple[str, int]]]:
    exa, tavily, deep = _Search("exa"), _Search("tavily"), _Search("deep")
    request = FastResearchInput(topic="an artist career", desired_duration_seconds=900, depth=depth)
    service = BackgroundResearchService(
        discovery=exa,
        research=tavily,
        deep_research=deep,
        planner=BackgroundResearchPlanner(PlannerFixture(_big_plan())),
        deadline_seconds=1.0,
    )
    asyncio.run(service.run(request, _fallback_fast(request)))
    return {"exa": exa.calls, "tavily": tavily.calls, "deep": deep.calls}


def test_a_standard_programme_searches_four_results_per_query_with_the_basic_provider() -> None:
    calls = _run(ResearchDepth.STANDARD)

    assert len(calls["exa"]) == 1 and len(calls["tavily"]) == 2 and calls["deep"] == []
    assert all(limit == 4 for _query, limit in [*calls["exa"], *calls["tavily"]])


def test_a_deep_programme_uses_the_advanced_provider_and_more_results() -> None:
    calls = _run(ResearchDepth.DEEP)

    assert len(calls["exa"]) == 2 and len(calls["deep"]) == 5 and calls["tavily"] == []
    assert all(limit == 5 for _query, limit in [*calls["exa"], *calls["deep"]])


def test_the_planner_is_told_the_budget_it_will_get() -> None:
    standard = BackgroundResearchPlanner._prompt(
        FastResearchInput(topic="t", desired_duration_seconds=900), _fallback_fast(FastResearchInput(topic="t", desired_duration_seconds=900))
    )
    deep = BackgroundResearchPlanner._prompt(
        FastResearchInput(topic="t", desired_duration_seconds=900, depth=ResearchDepth.DEEP),
        _fallback_fast(FastResearchInput(topic="t", desired_duration_seconds=900)),
    )

    assert "at most 1 DISCOVERY queries through Exa and 2 RESEARCH/EXACT" in standard
    assert "at most 2 DISCOVERY queries through Exa and 5 RESEARCH/EXACT" in deep


class _LongSearch:
    async def search(self, query: str, *, limit: int = 5, stage: str | None = None) -> list[SearchResult]:
        del limit, stage
        return [
            SearchResult(
                title=f"page about {query}",
                url=f"https://example.test/{query.replace(' ', '-')}",
                snippet="x" * 2500,
                content="y" * 2500,
                provider="tavily",
                query=query,
                score=0.8,
            )
        ]


def _excerpt_lengths(depth: ResearchDepth) -> set[int]:
    request = FastResearchInput(topic="an artist career", desired_duration_seconds=900, depth=depth)
    service = BackgroundResearchService(
        discovery=_LongSearch(),
        research=_LongSearch(),
        deep_research=_LongSearch(),
        planner=BackgroundResearchPlanner(PlannerFixture(_big_plan())),
        deadline_seconds=1.0,
    )
    bundle = asyncio.run(service.run(request, _fallback_fast(request)))
    assert bundle is not None and bundle.evidence
    return {len(item.claim_or_excerpt) for item in bundle.evidence}


def test_a_deep_programme_keeps_longer_excerpts_than_a_standard_one() -> None:
    assert _excerpt_lengths(ResearchDepth.STANDARD) == {800}
    assert _excerpt_lengths(ResearchDepth.DEEP) == {1600}
