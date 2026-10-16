"""The Exa-only search configuration: Tavily is never built, asked or required."""

from __future__ import annotations

import asyncio

import pytest
from wavecast.assembly import create_episode_assembly_service
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
    FastResearchService,
)
from wavecast.intelligence.trace import GenerationTrace
from wavecast.providers.config import ProviderSettings
from wavecast.providers.errors import ProviderConfigurationError
from wavecast.storage import LocalObjectStorageProvider

from tests.test_progressive_research import DelayedSearch, request


def test_the_backend_defaults_to_both_services_and_reads_one_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WAVECAST_SEARCH_BACKEND", raising=False)
    assert ProviderSettings.from_env().search_backend == "exa_tavily"
    monkeypatch.setenv("WAVECAST_SEARCH_BACKEND", "exa")
    assert ProviderSettings.from_env().search_backend == "exa"
    monkeypatch.setenv("WAVECAST_SEARCH_BACKEND", "tavily")
    with pytest.raises(ProviderConfigurationError, match="WAVECAST_SEARCH_BACKEND"):
        ProviderSettings.from_env()


def test_exa_only_builds_without_a_tavily_key_and_never_constructs_tavily(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    built: list[str] = []

    class Exa:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            built.append("exa")

    def tavily(*_args: object, **_kwargs: object) -> None:
        built.append("tavily")
        raise AssertionError("Tavily must not be built in the Exa-only configuration")

    monkeypatch.setattr("wavecast.assembly.ExaSearchProvider", Exa)
    monkeypatch.setattr("wavecast.assembly.TavilySearchProvider", tavily)
    service = create_episode_assembly_service(
        ProviderSettings(
            mode="mock", research_provider="live", research_plan_provider="mock", exa_api_key="k",
            search_backend="exa",
        ),
        storage=LocalObjectStorageProvider(tmp_path / "audio"),
    )

    research = service.background_pipeline.research
    assert built == ["exa"]
    assert research.research is research.discovery and research.deep_research is None
    assert research.research_label == "exa" and service.fast_path.research.research_label == "exa"
    assert research.planner.exa_only is True  # type: ignore[union-attr]


def test_the_default_configuration_still_builds_both_services(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    class Exa:
        def __init__(self, *_a: object, **_k: object) -> None: ...

    class Tavily:
        def __init__(self, *_a: object, **kwargs: object) -> None:
            self.depth = kwargs.get("search_depth", "basic")

    monkeypatch.setattr("wavecast.assembly.ExaSearchProvider", Exa)
    monkeypatch.setattr("wavecast.assembly.TavilySearchProvider", Tavily)
    service = create_episode_assembly_service(
        ProviderSettings(
            mode="mock", research_provider="live", research_plan_provider="mock", exa_api_key="k",
            tavily_api_key="t",
        ),
        storage=LocalObjectStorageProvider(tmp_path / "audio"),
    )

    research = service.background_pipeline.research
    assert isinstance(research.research, Tavily) and isinstance(research.deep_research, Tavily)
    assert research.deep_research.depth == "advanced" and research.research_label == "tavily"  # type: ignore[attr-defined]
    assert research.planner.exa_only is False  # type: ignore[union-attr]


def _empty_fast_result():  # type: ignore[no-untyped-def]
    from wavecast.intelligence.models import FastStartPlan, NarrationScript, ResearchBundle

    bundle = ResearchBundle(anchors=[], taste_hypotheses=[], evidence=[], candidates=[])
    plan = FastStartPlan(
        anchor_understanding=[], immediate_taste_hypotheses=[], next_candidates=[],
        first_narration=NarrationScript(text="-", intended_duration_seconds=1),
    )
    return type("Fast", (), {"bundle": bundle, "queries": [], "plan": plan})()


def test_the_planner_is_told_the_truth_about_where_its_queries_run() -> None:
    fast = _empty_fast_result()
    deep = FastResearchInput(topic="t", desired_duration_seconds=600, depth=ResearchDepth.DEEP)

    both = BackgroundResearchPlanner._prompt(deep, fast)  # type: ignore[arg-type]  # noqa: SLF001
    exa = BackgroundResearchPlanner._prompt(deep, fast, exa_only=True)  # type: ignore[arg-type]  # noqa: SLF001

    assert "2 DISCOVERY queries through Exa and 5 RESEARCH/EXACT queries through Tavily" in both
    assert "Tavily" not in exa
    assert "2 DISCOVERY and 5 RESEARCH/EXACT queries, all through Exa" in exa


def test_the_fast_stage_uses_both_slots_and_names_the_real_provider_on_failure() -> None:
    discovery = DelayedSearch("exa")
    research = DelayedSearch("exa", fail=True)
    service = FastResearchService(
        discovery=discovery, research=research, deadline_seconds=0.2, research_label="exa"
    )

    result = asyncio.run(service.run(request()))

    assert len(discovery.calls) == 1 and len(research.calls) == 1  # two Exa requests, as configured
    assert len(result.bundle.evidence) == 1
    assert result.bundle.uncertainties == ["exa unavailable: RuntimeError"]
    assert not any("tavily" in item for item in result.bundle.uncertainties)


def test_background_research_routes_every_query_to_exa_and_records_exa(monkeypatch: pytest.MonkeyPatch) -> None:
    exa = DelayedSearch("exa")
    plan = ResearchPlan(
        central_question="q",
        facets=[ResearchFacet(id="f", label="F", question="?", priority=1)],
        background_queries=[
            PlannedResearchQuery(query="one", intent=SearchIntent.DISCOVERY, facet_ids=["f"], rationale="r"),
            PlannedResearchQuery(query="two", intent=SearchIntent.RESEARCH, facet_ids=["f"], rationale="r"),
            PlannedResearchQuery(query="three", intent=SearchIntent.RESEARCH, facet_ids=["f"], rationale="r"),
        ],
    )

    class Planner:
        async def plan(self, *_a: object, **_k: object) -> ResearchPlan:
            return plan

    service = BackgroundResearchService(
        discovery=exa, research=exa, deep_research=None, planner=Planner(),  # type: ignore[arg-type]
        research_label="exa",
    )
    trace = GenerationTrace(request_id="t")
    fast_result = _empty_fast_result()
    bundle = asyncio.run(service.run(request(), fast_result, trace=trace))

    assert bundle is not None
    assert sorted(exa.calls) == ["one", "three", "two"]  # every query went to Exa
    started = next(e for e in trace.events if e.name == "background_started")
    assert {item["provider"] for item in started.metadata["selected_queries"]} == {"exa"}
