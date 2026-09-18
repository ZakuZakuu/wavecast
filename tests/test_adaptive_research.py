import asyncio
import json

from wavecast.intelligence.fast_start import FastStartPlanner, deterministic_fallback
from wavecast.intelligence.models import (
    FastResearchInput,
    FastResearchResult,
    FastStartPlan,
    NarrationScript,
    PlannedResearchQuery,
    ResearchBundle,
    ResearchFacet,
    ResearchPlan,
    ResearchPlanMode,
    SearchIntent,
)
from wavecast.intelligence.research import (
    BackgroundResearchService,
    build_fast_queries,
)
from wavecast.providers.contracts import SearchResult


class RecordingSearch:
    def __init__(self, provider: str, *, fail: bool = False) -> None:
        self.provider = provider
        self.fail = fail
        self.calls: list[str] = []

    async def search(
        self, query: str, *, limit: int = 5, stage: str | None = None
    ) -> list[SearchResult]:
        del limit, stage
        self.calls.append(query)
        if self.fail:
            raise RuntimeError("fixture failure")
        return [
            SearchResult(
                title=f"{self.provider} source",
                url=f"https://example.test/{self.provider}/{len(self.calls)}",
                snippet="normalized source",
                provider=self.provider,
                query=query,
                score=0.8,
            )
        ]


def request() -> FastResearchInput:
    return FastResearchInput(
        topic="the history of bedroom production",
        anchor_tracks=["Anchor — Opening"],
        desired_duration_seconds=900,
    )


def plan(*queries: PlannedResearchQuery) -> ResearchPlan:
    return ResearchPlan(
        central_question="How did this topic develop and what evidence explains it?",
        facets=[
            ResearchFacet(
                id="history",
                label="History",
                question="What context explains the development?",
                priority=90,
                source_preferences=["primary", "interview"],
            )
        ],
        background_queries=list(queries),
    )


def fast_result(research_plan: ResearchPlan, queries: list[str] | None = None) -> FastResearchResult:
    return FastResearchResult(
        bundle=ResearchBundle(
            anchors=request().anchor_tracks,
            taste_hypotheses=[],
            evidence=[],
            candidates=[],
        ),
        elapsed_ms=0,
        queries=queries or [],
    )


def test_fast_queries_are_topic_adaptive_without_forced_similarity_dimensions() -> None:
    discovery, research = build_fast_queries(request())

    assert "bedroom production" in discovery
    assert "bedroom production" in research
    assert "groove harmony production texture" not in discovery
    assert "same-artist" not in research


def test_background_routes_one_two_or_three_planned_queries_and_deduplicates_fast() -> None:
    async def run() -> tuple[RecordingSearch, RecordingSearch, list[object]]:
        exa = RecordingSearch("exa")
        tavily = RecordingSearch("tavily")
        service = BackgroundResearchService(discovery=exa, research=tavily, deadline_seconds=0.2)
        research_plan = plan(
            PlannedResearchQuery(
                query="already fast",
                intent=SearchIntent.RESEARCH,
                facet_ids=["history"],
                rationale="avoid duplicate work",
            ),
            PlannedResearchQuery(
                query="discover context",
                intent=SearchIntent.DISCOVERY,
                facet_ids=["history"],
                rationale="find adjacent context",
            ),
            PlannedResearchQuery(
                query="exact history source",
                intent=SearchIntent.EXACT,
                facet_ids=["history"],
                rationale="verify a detail",
            ),
        )
        result = await service.run(
            request(),
            _fast_path_result(research_plan, queries=["already fast"]),
        )
        assert result is not None
        return exa, tavily, list(result.evidence)

    exa, tavily, evidence = asyncio.run(run())
    assert exa.calls == ["discover context"]
    assert tavily.calls == ["exact history source"]
    assert [item.search_intent for item in evidence] == [SearchIntent.DISCOVERY, SearchIntent.EXACT]
    assert all(item.facet_ids == ["history"] for item in evidence)
    assert [item.source_title for item in evidence] == ["exa source", "tavily source"]


def test_background_provider_failure_isolated_and_two_queries_are_safe() -> None:
    async def run() -> tuple[RecordingSearch, RecordingSearch, int]:
        exa = RecordingSearch("exa", fail=True)
        tavily = RecordingSearch("tavily")
        service = BackgroundResearchService(discovery=exa, research=tavily, deadline_seconds=0.2)
        result = await service.run(
            request(),
            _fast_path_result(
                plan(
                    PlannedResearchQuery(
                        query="one", intent=SearchIntent.DISCOVERY, rationale="context"
                    ),
                    PlannedResearchQuery(
                        query="two", intent=SearchIntent.RESEARCH, rationale="evidence"
                    ),
                )
            ),
        )
        assert result is not None
        return exa, tavily, len(result.evidence)

    exa, tavily, evidence_count = asyncio.run(run())
    assert exa.calls == ["one"]
    assert tavily.calls == ["two"]
    assert evidence_count == 1


def test_background_never_exceeds_one_exa_and_two_tavily_calls() -> None:
    async def run() -> tuple[list[str], list[str]]:
        exa = RecordingSearch("exa")
        tavily = RecordingSearch("tavily")
        service = BackgroundResearchService(discovery=exa, research=tavily, deadline_seconds=0.2)
        await service.run(
            request(),
            _fast_path_result(
                plan(
                    PlannedResearchQuery(
                        query="discover", intent=SearchIntent.DISCOVERY, rationale="one"
                    ),
                    PlannedResearchQuery(
                        query="research", intent=SearchIntent.RESEARCH, rationale="two"
                    ),
                    PlannedResearchQuery(
                        query="exact", intent=SearchIntent.EXACT, rationale="three"
                    ),
                )
            ),
        )
        return exa.calls, tavily.calls

    exa_calls, tavily_calls = asyncio.run(run())
    assert exa_calls == ["discover"]
    assert tavily_calls == ["research", "exact"]


def test_larger_proposal_pool_is_trimmed_only_at_execution_boundary() -> None:
    async def run() -> tuple[list[str], list[str]]:
        exa = RecordingSearch("exa")
        tavily = RecordingSearch("tavily")
        service = BackgroundResearchService(discovery=exa, research=tavily, deadline_seconds=0.2)
        await service.run(
            request(),
            _fast_path_result(
                plan(
                    PlannedResearchQuery(
                        query="discovery-1", intent=SearchIntent.DISCOVERY, rationale="first"
                    ),
                    PlannedResearchQuery(
                        query="discovery-2", intent=SearchIntent.DISCOVERY, rationale="second"
                    ),
                    PlannedResearchQuery(
                        query="research-1", intent=SearchIntent.RESEARCH, rationale="third"
                    ),
                    PlannedResearchQuery(
                        query="exact-1", intent=SearchIntent.EXACT, rationale="fourth"
                    ),
                    PlannedResearchQuery(
                        query="research-2", intent=SearchIntent.RESEARCH, rationale="fifth"
                    ),
                )
            ),
        )
        return exa.calls, tavily.calls

    exa_calls, tavily_calls = asyncio.run(run())
    assert exa_calls == ["discovery-1"]
    assert tavily_calls == ["research-1", "exact-1"]


def test_omitted_research_plan_is_normalized_to_generic_plan() -> None:
    class OmittedPlanLLM:
        async def structured(self, _prompt: str, _output_type: type[object], **_: object) -> object:
            return FastStartPlan(
                anchor_understanding=[],
                immediate_taste_hypotheses=[],
                next_candidates=[],
                first_narration=NarrationScript(text="fixture", intended_duration_seconds=5),
            )

    result = asyncio.run(
        FastStartPlanner(OmittedPlanLLM()).plan(
            request(),
            fast_result(ResearchPlan(central_question="unused")),
        )
    )

    assert result.research_plan.facets[0].id == "context"
    assert request().topic in result.research_plan.central_question
    assert result.research_plan.background_queries


def test_explicit_no_additional_research_plan_remains_intentionally_empty() -> None:
    explicit = ResearchPlan(
        central_question="No background evidence is needed.",
        research_mode=ResearchPlanMode.NO_ADDITIONAL_RESEARCH,
        no_research_reason="The listener asked for a short context-free playback.",
    )

    class ExplicitPlanLLM:
        async def structured(self, _prompt: str, _output_type: type[object], **_: object) -> object:
            return FastStartPlan(
                anchor_understanding=[],
                immediate_taste_hypotheses=[],
                next_candidates=[],
                first_narration=NarrationScript(text="fixture", intended_duration_seconds=5),
                research_plan=explicit,
            )

    result = asyncio.run(
        FastStartPlanner(ExplicitPlanLLM()).plan(
            request(),
            fast_result(ResearchPlan(central_question="unused")),
        )
    )

    assert result.research_plan == explicit
    assert result.research_plan.background_queries == []


def test_background_cancellation_stops_in_flight_planned_queries() -> None:
    async def run() -> tuple[asyncio.Event, object]:
        cancel = asyncio.Event()

        class BlockingSearch(RecordingSearch):
            async def search(
                self, query: str, *, limit: int = 5, stage: str | None = None
            ) -> list[SearchResult]:
                self.calls.append(query)
                await cancel.wait()
                return []

        exa = BlockingSearch("exa")
        tavily = BlockingSearch("tavily")
        service = BackgroundResearchService(discovery=exa, research=tavily, deadline_seconds=1)
        operation = asyncio.create_task(
            service.run(
                request(),
                _fast_path_result(
                    plan(
                        PlannedResearchQuery(
                            query="cancel me", intent=SearchIntent.DISCOVERY, rationale="fixture"
                        )
                    )
                ),
                cancel_event=cancel,
            )
        )
        await asyncio.sleep(0)
        cancel.set()
        return cancel, await operation

    _, result = asyncio.run(run())
    assert result is None


def test_fallback_contains_generic_research_plan_without_music_template() -> None:
    research = fast_result(ResearchPlan(central_question="What matters?"))
    fallback = deterministic_fallback(request(), research)

    assert fallback.research_plan.background_queries
    serialized = fallback.research_plan.model_dump_json()
    assert "groove" not in serialized
    assert "same-artist" not in serialized
    assert request().topic in serialized


def test_research_plans_remain_structurally_topic_adaptive_for_five_request_shapes() -> None:
    shapes = {
        "career": [SearchIntent.RESEARCH, SearchIntent.EXACT],
        "creation": [SearchIntent.RESEARCH],
        "analysis": [SearchIntent.RESEARCH, SearchIntent.RESEARCH, SearchIntent.EXACT],
        "history": [SearchIntent.EXACT],
        "discovery": [SearchIntent.DISCOVERY, SearchIntent.RESEARCH],
    }

    class ShapeLLM:
        async def structured(self, prompt: str, output_type: type[object], **_: object) -> object:
            del output_type
            request_payload = json.loads(prompt.split("Request: ", 1)[1].split("\nResearch:", 1)[0])
            shape = request_payload["topic"].split()[0]
            research_plan = ResearchPlan(
                central_question=f"What explains this {shape} request?",
                facets=[
                    ResearchFacet(
                        id=shape,
                        label=shape.title(),
                        question=f"What evidence addresses the {shape} question?",
                        priority=90,
                    )
                ],
                background_queries=[
                    PlannedResearchQuery(
                        query=f"{shape} evidence {index}",
                        intent=intent,
                        facet_ids=[shape],
                        rationale="fixture plan",
                    )
                    for index, intent in enumerate(shapes[shape])
                ],
            )
            return FastStartPlan(
                anchor_understanding=[shape],
                immediate_taste_hypotheses=[],
                next_candidates=[],
                first_narration=NarrationScript(text="fixture", intended_duration_seconds=5),
                research_plan=research_plan,
            )

    planner = FastStartPlanner(ShapeLLM())
    plans = []
    for shape in shapes:
        shaped_request = FastResearchInput(
            topic=f"{shape} request",
            desired_duration_seconds=600,
        )
        empty_research = FastResearchResult(
            bundle=ResearchBundle(anchors=[], taste_hypotheses=[], evidence=[], candidates=[]),
            elapsed_ms=0,
            queries=[],
        )
        plans.append(asyncio.run(planner.plan(shaped_request, empty_research)))

    assert len({plan.research_plan.central_question for plan in plans}) == 5
    assert [len(plan.research_plan.background_queries) for plan in plans] == [2, 1, 3, 1, 2]
    assert all(len(plan.research_plan.background_queries) <= 3 for plan in plans)


def _fast_path_result(research_plan: ResearchPlan, queries: list[str] | None = None):
    from wavecast.intelligence.fast_start import FastPathResult
    from wavecast.intelligence.models import FastStartPlan, NarrationScript
    from wavecast.intelligence.trace import GenerationTrace

    return FastPathResult(
        research=fast_result(research_plan, queries),
        plan=FastStartPlan(
            anchor_understanding=[],
            immediate_taste_hypotheses=[],
            next_candidates=[],
            first_narration=NarrationScript(text="start", intended_duration_seconds=5),
            research_plan=research_plan,
        ),
        trace=GenerationTrace(request_id="adaptive"),
        elapsed_ms=0,
    )
