import asyncio
import json

import pytest
from wavecast.assembly import create_episode_assembly_service
from wavecast.intelligence.curation import CuratorService
from wavecast.intelligence.fast_start import FastPathResult
from wavecast.intelligence.models import (
    ClaimSupport,
    ClaimType,
    Evidence,
    EvidenceSourceCategory,
    FastResearchInput,
    FastStartPlan,
    NarrationScript,
    NarrativeRole,
    NoveltyDistance,
    PlannedResearchQuery,
    ProgramSkeleton,
    RadioScript,
    RadioScriptBlock,
    RadioScriptBlockKind,
    ResearchBundle,
    ResearchFacet,
    ResearchPlan,
    ResearchPlanMode,
    SearchIntent,
    TrackProposal,
)
from wavecast.intelligence.research import (
    BackgroundResearchPlanner,
    BackgroundResearchService,
    bundle_from_results,
    canonicalize_url,
    generic_research_plan,
    normalize_results,
)
from wavecast.intelligence.trace import GenerationTrace
from wavecast.providers.contracts import SearchResult
from wavecast.providers.errors import ProviderInvalidResponseError

from scripts import live_episode_probe


def _request(topic: str = "an artist career history") -> FastResearchInput:
    return FastResearchInput(topic=topic, desired_duration_seconds=900)


def _fallback_fast(request: FastResearchInput) -> FastPathResult:
    trace = GenerationTrace(request_id="fallback")
    trace.mark("fallback_used", reason="deadline")
    return FastPathResult(
        research=type("Research", (), {"bundle": ResearchBundle(anchors=[], taste_hypotheses=[], evidence=[], candidates=[]), "queries": []})(),  # type: ignore[arg-type]
        plan=FastStartPlan(
            anchor_understanding=[],
            immediate_taste_hypotheses=[],
            next_candidates=[],
            first_narration=NarrationScript(text="start", intended_duration_seconds=5),
        ),
        trace=trace,
        elapsed_ms=0,
    )


def _adaptive_plan() -> ResearchPlan:
    return ResearchPlan(
        central_question="How did the artist's early work lead to a wider audience?",
        facets=[
            ResearchFacet(
                id="origins",
                label="Early origins",
                question="What early activity established the artist's path?",
                priority=90,
                source_preferences=["interview", "reference"],
            ),
            ResearchFacet(
                id="breakout",
                label="Breakout",
                question="What evidence explains the later audience expansion?",
                priority=80,
                source_preferences=["primary", "news"],
            ),
        ],
        background_queries=[
            PlannedResearchQuery(
                query="early activity primary interview",
                intent=SearchIntent.RESEARCH,
                facet_ids=["origins"],
                rationale="ground the origin story",
            ),
            PlannedResearchQuery(
                query="audience expansion exact references",
                intent=SearchIntent.EXACT,
                facet_ids=["breakout"],
                rationale="verify the breakout claim",
            ),
        ],
    )


class PlannerFixture:
    def __init__(self, output: object | None = None, *, fail: bool = False) -> None:
        self.output = output or _adaptive_plan()
        self.fail = fail
        self.calls: list[dict[str, object]] = []

    async def structured(self, prompt: str, output_type: type[object], **kwargs: object) -> object:
        self.calls.append({"prompt": prompt, "output_type": output_type, **kwargs})
        if self.fail:
            raise RuntimeError("fixture planner failure")
        return self.output


class RecordingSearch:
    def __init__(self, provider: str) -> None:
        self.provider = provider
        self.calls: list[str] = []

    async def search(
        self, query: str, *, limit: int = 5, stage: str | None = None
    ) -> list[SearchResult]:
        del limit, stage
        self.calls.append(query)
        return [
            SearchResult(
                title=f"{self.provider} result",
                url=f"https://example.test/{self.provider}/{len(self.calls)}?utm_source=fixture",
                snippet="fixture evidence",
                provider=self.provider,
                query=query,
                score=0.8,
            )
        ]


def test_background_planner_regenerates_after_fast_fallback_and_routes_its_plan() -> None:
    async def run() -> tuple[PlannerFixture, RecordingSearch, RecordingSearch, GenerationTrace, ResearchBundle]:
        planner_llm = PlannerFixture()
        exa = RecordingSearch("exa")
        tavily = RecordingSearch("tavily")
        service = BackgroundResearchService(
            discovery=exa,
            research=tavily,
            planner=BackgroundResearchPlanner(planner_llm),
            deadline_seconds=0.2,
        )
        fast = _fallback_fast(_request())
        trace = GenerationTrace(request_id="planner")
        bundle = await service.run(_request(), fast, trace=trace)
        assert bundle is not None
        return planner_llm, exa, tavily, trace, bundle

    planner_llm, exa, tavily, trace, bundle = asyncio.run(run())
    assert len(planner_llm.calls) == 1
    assert planner_llm.calls[0]["stage"] == "research_planner"
    assert exa.calls == []
    assert tavily.calls == [
        "early activity primary interview",
        "audience expansion exact references",
    ]
    assert bundle.research_plan == _adaptive_plan()
    assert any(event.name == "background_research_plan_regenerated" for event in trace.events)


def test_background_planner_failure_uses_generic_plan_without_blocking_search() -> None:
    async def run() -> tuple[PlannerFixture, RecordingSearch, ResearchBundle, GenerationTrace]:
        planner_llm = PlannerFixture(fail=True)
        tavily = RecordingSearch("tavily")
        service = BackgroundResearchService(
            discovery=RecordingSearch("exa"),
            research=tavily,
            planner=BackgroundResearchPlanner(planner_llm),
            deadline_seconds=0.2,
        )
        trace = GenerationTrace(request_id="planner-fallback")
        bundle = await service.run(_request(), _fallback_fast(_request()), trace=trace)
        assert bundle is not None
        return planner_llm, tavily, bundle, trace

    planner_llm, tavily, bundle, trace = asyncio.run(run())
    assert len(planner_llm.calls) == 1
    assert tavily.calls
    assert bundle.research_plan is not None
    assert bundle.research_plan.facets[0].id == "context"
    assert any(event.name == "background_research_plan_fallback" for event in trace.events)


def test_background_planner_rejects_empty_adaptive_output_and_uses_generic_fallback() -> None:
    async def run() -> tuple[PlannerFixture, RecordingSearch, RecordingSearch, GenerationTrace, ResearchBundle]:
        planner_llm = PlannerFixture(
            output=ResearchPlan(
                central_question="planner forgot the research intent",
                research_mode=ResearchPlanMode.ADAPTIVE,
                facets=[],
                background_queries=[],
            )
        )
        exa = RecordingSearch("exa")
        tavily = RecordingSearch("tavily")
        service = BackgroundResearchService(
            discovery=exa,
            research=tavily,
            planner=BackgroundResearchPlanner(planner_llm),
            deadline_seconds=0.2,
        )
        trace = GenerationTrace(request_id="planner-empty-adaptive")
        bundle = await service.run(_request(), _fallback_fast(_request()), trace=trace)
        assert bundle is not None
        return planner_llm, exa, tavily, trace, bundle

    planner_llm, exa, tavily, trace, bundle = asyncio.run(run())
    assert len(planner_llm.calls) == 1
    assert exa.calls == [generic_research_plan(_request()).background_queries[0].query]
    assert tavily.calls == [
        query.query for query in generic_research_plan(_request()).background_queries[1:]
    ]
    assert bundle.research_plan == generic_research_plan(_request())
    fallback_events = [
        event for event in trace.events if event.name == "background_research_plan_fallback"
    ]
    assert len(fallback_events) == 1
    assert fallback_events[0].metadata["reason"] == "ProviderInvalidResponseError"


def test_useful_fast_plan_does_not_trigger_background_planner() -> None:
    async def run() -> PlannerFixture:
        planner_llm = PlannerFixture()
        service = BackgroundResearchService(
            discovery=RecordingSearch("exa"),
            research=RecordingSearch("tavily"),
            planner=BackgroundResearchPlanner(planner_llm),
            deadline_seconds=0.2,
        )
        fast = _fallback_fast(_request())
        fast.trace.events.clear()
        fast.plan = fast.plan.model_copy(update={"research_plan": _adaptive_plan()})
        await service.run(_request(), fast)
        return planner_llm

    assert asyncio.run(run()).calls == []


def test_effectively_empty_fast_research_plan_triggers_regeneration() -> None:
    async def run() -> tuple[PlannerFixture, ResearchBundle]:
        planner_llm = PlannerFixture()
        service = BackgroundResearchService(
            discovery=RecordingSearch("exa"),
            research=RecordingSearch("tavily"),
            planner=BackgroundResearchPlanner(planner_llm),
            deadline_seconds=0.2,
        )
        fast = _fallback_fast(_request())
        fast.trace.events.clear()
        fast.plan = fast.plan.model_copy(
            update={"research_plan": ResearchPlan(central_question="intentionally empty")}
        )
        bundle = await service.run(_request(), fast)
        assert bundle is not None
        return planner_llm, bundle

    planner_llm, bundle = asyncio.run(run())
    assert len(planner_llm.calls) == 1
    assert bundle.research_plan == _adaptive_plan()


def test_explicit_no_additional_research_plan_skips_regeneration() -> None:
    async def run() -> tuple[PlannerFixture, ResearchBundle, RecordingSearch, RecordingSearch]:
        planner_llm = PlannerFixture()
        exa = RecordingSearch("exa")
        tavily = RecordingSearch("tavily")
        service = BackgroundResearchService(
            discovery=exa,
            research=tavily,
            planner=BackgroundResearchPlanner(planner_llm),
            deadline_seconds=0.2,
        )
        fast = _fallback_fast(_request())
        fast.trace.events.clear()
        intentional = ResearchPlan(
            central_question="intentionally empty",
            research_mode=ResearchPlanMode.NO_ADDITIONAL_RESEARCH,
            no_research_reason="The topic is already fully specified by the listener.",
        )
        fast.plan = fast.plan.model_copy(update={"research_plan": intentional})
        bundle = await service.run(_request(), fast)
        assert bundle is not None
        return planner_llm, bundle, exa, tavily

    planner_llm, bundle, exa, tavily = asyncio.run(run())
    assert planner_llm.calls == []
    assert exa.calls == []
    assert tavily.calls == []
    assert bundle.research_plan == ResearchPlan(
        central_question="intentionally empty",
        research_mode=ResearchPlanMode.NO_ADDITIONAL_RESEARCH,
        no_research_reason="The topic is already fully specified by the listener.",
    )


def test_no_additional_research_mode_requires_a_reason() -> None:
    with pytest.raises(ValueError, match="no_research_reason"):
        ResearchPlan(
            central_question="intentional",
            research_mode=ResearchPlanMode.NO_ADDITIONAL_RESEARCH,
        )


def test_background_planner_honors_cancellation_without_search_calls() -> None:
    class BlockingPlanner:
        async def plan(self, *_args: object, **_kwargs: object) -> ResearchPlan:
            await asyncio.Future()
            raise AssertionError("unreachable")

    async def run() -> tuple[asyncio.Event, object, RecordingSearch, RecordingSearch]:
        cancel = asyncio.Event()
        exa = RecordingSearch("exa")
        tavily = RecordingSearch("tavily")
        service = BackgroundResearchService(
            discovery=exa,
            research=tavily,
            planner=BlockingPlanner(),
            deadline_seconds=1,
        )
        operation = asyncio.create_task(
            service.run(_request(), _fallback_fast(_request()), cancel_event=cancel)
        )
        await asyncio.sleep(0)
        cancel.set()
        return cancel, await operation, exa, tavily

    _, result, exa, tavily = asyncio.run(run())
    assert result is None
    assert exa.calls == []
    assert tavily.calls == []


def test_research_planner_prompt_is_topic_adaptive_and_distinguishes_claim_types() -> None:
    planner = BackgroundResearchPlanner(PlannerFixture())
    prompt = planner._prompt(_request("creative process behind a landmark album"), _fallback_fast(_request()))

    assert "creative process behind a landmark album" in prompt
    assert "fact" in prompt
    assert "correlation" in prompt
    assert "causal claim" in prompt
    assert "editorial interpretation" in prompt


def test_evidence_urls_are_canonicalized_before_deduplication_and_id_generation() -> None:
    first = SearchResult(
        title="Source",
        url="HTTPS://Example.TEST/story?utm_source=exa&b=2&a=1#section",
        snippet="one",
        provider="exa",
        query="q",
    )
    second = first.model_copy(
        update={
            "url": "https://example.test/story?a=1&b=2&utm_medium=tavily",
            "provider": "tavily",
        }
    )

    normalized = normalize_results([first, second])
    bundle = bundle_from_results(_request(), normalized, [], query_context={})

    assert canonicalize_url(first.url) == "https://example.test/story?a=1&b=2"
    assert len(bundle.evidence) == 1
    assert bundle.evidence[0].canonical_url == "https://example.test/story?a=1&b=2"
    assert bundle.evidence[0].source_domain == "example.test"
    assert bundle.evidence[0].source_category is EvidenceSourceCategory.UNKNOWN


def test_canonicalization_does_not_merge_non_root_trailing_slash_paths() -> None:
    results = [
        SearchResult(
            title="Without slash",
            url="https://example.test/resource",
            snippet="one",
            provider="fixture",
            query="q",
        ),
        SearchResult(
            title="With slash",
            url="https://example.test/resource/",
            snippet="two",
            provider="fixture",
            query="q",
        ),
    ]

    normalized = normalize_results(results)

    assert [item.url for item in normalized] == [
        "https://example.test/resource",
        "https://example.test/resource/",
    ]


def test_source_preferences_do_not_invent_primary_authority() -> None:
    plan = ResearchPlan(
        central_question="fixture provenance",
        facets=[
            ResearchFacet(
                id="context",
                label="Context",
                question="Which sources ground the claim?",
                priority=80,
                source_preferences=["primary", "interview", "reference"],
            )
        ],
        background_queries=[
            PlannedResearchQuery(
                query="q",
                intent=SearchIntent.RESEARCH,
                facet_ids=["context"],
                rationale="fixture",
            )
        ],
    )
    results = [
        SearchResult(
            title="Catalog",
            url="https://musicbrainz.org/recording/1",
            snippet="catalog",
            provider="fixture",
            query="q",
            score=0.2,
        ),
        SearchResult(
            title="Institution",
            url="https://archive.example.edu/page",
            snippet="institution",
            provider="fixture",
            query="q",
            score=0.9,
        ),
        SearchResult(
            title="Reference",
            url="https://en.wikipedia.org/wiki/Example",
            snippet="reference",
            provider="fixture",
            query="q",
            score=0.4,
        ),
    ]

    bundle = bundle_from_results(
        _request(),
        results,
        [],
        query_context={"q": plan.background_queries[0]},
        research_plan=plan,
    )

    assert bundle.evidence[0].source_category is EvidenceSourceCategory.REFERENCE
    assert all(
        item.source_category is not EvidenceSourceCategory.REFERENCE
        or item.source_preference_rank == 2
        for item in bundle.evidence
    )
    assert {item.confidence for item in bundle.evidence} == {0.2, 0.4, 0.9}


def test_source_provenance_is_conservative_and_preferences_only_rank_evidence() -> None:
    plan = _adaptive_plan()
    query = plan.background_queries[0]
    results = [
        SearchResult(
            title="Video",
            url="https://www.youtube.com/watch?v=1",
            snippet="video",
            provider="tavily",
            query=query.query,
        ),
        SearchResult(
            title="Reference",
            url="https://en.wikipedia.org/wiki/Example",
            snippet="reference",
            provider="tavily",
            query=query.query,
        ),
    ]
    bundle = bundle_from_results(
        _request(),
        results,
        [],
        query_context={query.query: query},
        research_plan=plan,
    )

    assert {item.source_category for item in bundle.evidence} == {
        EvidenceSourceCategory.VIDEO,
        EvidenceSourceCategory.REFERENCE,
    }
    assert all(item.source_preference_rank is not None for item in bundle.evidence)
    assert all(item.confidence == 0.5 for item in bundle.evidence)
    assert bundle.evidence[0].source_category is EvidenceSourceCategory.REFERENCE


def test_curator_claim_support_must_use_chapter_scoped_evidence() -> None:
    chapter = _chapter(evidence_ids=["e1"]).model_copy(
        update={
            "claim_support": [
                ClaimSupport(
                    claim_type=ClaimType.CAUSAL,
                    claim="unsupported causal link",
                    evidence_ids=["e2"],
                )
            ]
        }
    )
    skeleton = ProgramSkeleton(
        thesis="fixture",
        chapters=[chapter],
        estimated_duration_seconds=60,
    )

    class Fixture:
        async def structured(self, _prompt: str, _output_type: type[object], **_kwargs: object) -> object:
            return skeleton

    with pytest.raises(ProviderInvalidResponseError, match="claim support"):
        asyncio.run(
            CuratorService(Fixture()).curate(
                ResearchBundle(
                    anchors=[],
                    taste_hypotheses=[],
                    evidence=[_evidence("e1")],
                    candidates=[],
                ),
                FastStartPlan(
                    anchor_understanding=[],
                    immediate_taste_hypotheses=[],
                    next_candidates=[],
                    first_narration=NarrationScript(text="start", intended_duration_seconds=5),
                ),
                desired_duration_seconds=60,
            )
        )


def test_writer_claim_support_rejects_unknown_or_out_of_scope_evidence() -> None:
    chapter = _chapter(evidence_ids=["e1"])
    script = RadioScript(
        blocks=[
            RadioScriptBlock(
                kind=RadioScriptBlockKind.TRANSITION,
                text="A supported beat",
                duration_seconds=5,
                claim_support=[
                    ClaimSupport(
                        claim_type=ClaimType.FACT,
                        claim="supported",
                        evidence_ids=["e2"],
                    )
                ],
            )
        ]
    )

    class Fixture:
        async def structured(self, _prompt: str, _output_type: type[object], **_kwargs: object) -> object:
            return script

    from wavecast.intelligence.writer import WriterService

    with pytest.raises(ProviderInvalidResponseError, match="evidence"):
        asyncio.run(
            WriterService(Fixture()).write(
                chapter,
                [_evidence("e1")],
            )
        )


def test_writer_rejects_unknown_chapter_evidence_even_without_support_metadata() -> None:
    chapter = _chapter(evidence_ids=["ghost"])

    class Fixture:
        async def structured(self, _prompt: str, _output_type: type[object], **_kwargs: object) -> object:
            return NarrationScript(text="unsupported", intended_duration_seconds=5)

    from wavecast.intelligence.writer import WriterService

    with pytest.raises(ProviderInvalidResponseError, match="unavailable evidence"):
        asyncio.run(WriterService(Fixture()).write(chapter, []))


def test_claim_support_requires_non_empty_evidence_ids() -> None:
    with pytest.raises(ValueError):
        ClaimSupport(claim_type=ClaimType.FACT, claim="fixture", evidence_ids=[""])


def test_success_report_includes_skeleton_provenance_and_stage_usage(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = asyncio.run(
        create_episode_assembly_service().assemble(
            __import__("wavecast.assembly", fromlist=["LiveEpisodeAssemblyRequest"]).LiveEpisodeAssemblyRequest(
                topic="mock research quality",
                max_tracks=4,
            )
        )
    )
    report = live_episode_probe._report(result)

    assert report["program_skeleton"]["chapters"]
    assert "research_evidence" in report
    assert "usage_by_stage" in report
    assert "provider_events" in report
    serialized = json.dumps(report)
    assert "prompt" not in serialized
    assert "response" not in serialized


def _evidence(evidence_id: str) -> Evidence:
    return Evidence(
        id=evidence_id,
        claim_or_excerpt="supported evidence",
        source_url="https://example.test/source",
        canonical_url="https://example.test/source",
        source_domain="example.test",
        source_category=EvidenceSourceCategory.UNKNOWN,
        source_provider="fixture",
        confidence=0.8,
        query="fixture",
    )


def _chapter(*, evidence_ids: list[str]) -> object:
    return __import__("wavecast.intelligence.models", fromlist=["ChapterPlan"]).ChapterPlan(
        index=0,
        track=TrackProposal(artist="Artist", title="Track", confidence=0.8),
        narrative_role=NarrativeRole.ANCHOR,
        reason="fixture",
        novelty_distance=NoveltyDistance.CLOSE,
        evidence_ids=evidence_ids,
        narration_goal="introduce",
    )
