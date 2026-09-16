import asyncio

from wavecast.intelligence.fast_start import FastPathCoordinator, FastStartPlanner
from wavecast.intelligence.models import (
    FastResearchInput,
    FastResearchResult,
    FastStartPlan,
    NarrationScript,
    ResearchBundle,
)
from wavecast.intelligence.research import FastResearchService
from wavecast.providers.contracts import SearchResult
from wavecast.providers.profiles import InferenceProfile, StructuredTransport


class SearchFixture:
    async def search(
        self, query: str, *, limit: int = 5, stage: str | None = None
    ) -> list[SearchResult]:
        del limit
        del stage
        return [
            SearchResult(
                title="Fixture Artist - Fixture Track",
                url=f"https://example.test/{len(query)}",
                snippet="bounded evidence",
                provider="fixture",
                query=query,
                score=0.8,
            )
        ]


class RecordingLLM:
    def __init__(self, *, delay: float = 0) -> None:
        self.delay = delay
        self.calls: list[dict[str, object]] = []

    async def structured(self, prompt: str, output_type: type[object], **kwargs: object) -> object:
        self.calls.append({"prompt": prompt, **kwargs})
        await asyncio.sleep(self.delay)
        return FastStartPlan(
            anchor_understanding=["fixture"],
            immediate_taste_hypotheses=[],
            next_candidates=[],
            first_narration=NarrationScript(text="A useful start.", intended_duration_seconds=8),
        )


class FailingLLM(RecordingLLM):
    async def structured(self, prompt: str, output_type: type[object], **kwargs: object) -> object:
        self.calls.append({"prompt": prompt, **kwargs})
        raise RuntimeError("fixture provider failure")


def input_request() -> FastResearchInput:
    return FastResearchInput(
        topic="guided listening",
        anchor_tracks=["Anchor - Opening"],
        desired_duration_seconds=1200,
    )


def test_fast_planner_uses_one_responses_fast_call() -> None:
    llm = RecordingLLM()
    service = FastResearchService(
        discovery=SearchFixture(), research=SearchFixture(), deadline_seconds=0.2
    )
    coordinator = FastPathCoordinator(
        research=service, planner=FastStartPlanner(llm), deadline_seconds=1
    )

    result = asyncio.run(coordinator.run(input_request(), request_id="request-1"))

    assert len(llm.calls) == 1
    assert llm.calls[0]["transport"] is StructuredTransport.RESPONSES_JSON_SCHEMA
    assert llm.calls[0]["profile"] is InferenceProfile.FAST
    assert not result.trace.fallback_used
    assert result.trace.time_to_first_script_ms is not None
    assert result.trace.events[-1].name == "first_script_ready"
    assert result.trace.events[-1].metadata["fallback"] is False
    assert [event.name for event in result.trace.events].index("fast_research_done") < [
        event.name for event in result.trace.events
    ].index("fast_planner_started")
    assert result.trace.fast_research_elapsed_ms is not None
    assert result.trace.fast_planner_started_ms is not None
    plan_events = [event for event in result.trace.events if event.name == "research_plan_ready"]
    assert plan_events[0].metadata["research_facet_count"] == 1
    assert plan_events[0].metadata["planned_background_query_count"] == 3


def test_fast_prompt_is_topic_adaptive_and_declares_research_planning() -> None:
    planner = FastStartPlanner(RecordingLLM())
    research = FastResearchResult(
        bundle=ResearchBundle(anchors=[], taste_hypotheses=[], evidence=[], candidates=[]),
        elapsed_ms=0,
        queries=[],
    )

    prompt = planner._prompt(input_request(), research)

    assert "career, a creative work" in prompt
    assert "history/context, or discovery" in prompt
    assert "ResearchPlan" in prompt
    assert "Do not force similarity" in prompt


def test_fast_path_deadline_returns_safe_fallback_without_retry() -> None:
    llm = RecordingLLM(delay=0.2)
    service = FastResearchService(
        discovery=SearchFixture(), research=SearchFixture(), deadline_seconds=0.01
    )
    coordinator = FastPathCoordinator(
        research=service, planner=FastStartPlanner(llm), deadline_seconds=0.05
    )

    result = asyncio.run(coordinator.run(input_request(), request_id="request-2"))

    assert len(llm.calls) == 1
    assert result.trace.fallback_used
    assert result.trace.time_to_first_script_ms is not None
    assert result.plan.first_narration.text.startswith("We will start with Anchor - Opening")
    assert "Fixture Artist" not in result.plan.first_narration.text
    assert any(event.name == "first_script_ready" for event in result.trace.events)
    assert result.trace.fast_research_elapsed_ms is not None


def test_provider_failure_fallback_records_first_script_ready() -> None:
    llm = FailingLLM()
    service = FastResearchService(
        discovery=SearchFixture(), research=SearchFixture(), deadline_seconds=0.2
    )
    coordinator = FastPathCoordinator(
        research=service, planner=FastStartPlanner(llm), deadline_seconds=1
    )

    result = asyncio.run(coordinator.run(input_request(), request_id="request-3"))

    assert result.trace.fallback_used
    assert result.trace.time_to_first_script_ms is not None
    ready = [event for event in result.trace.events if event.name == "first_script_ready"]
    assert len(ready) == 1
    assert ready[0].metadata["fallback"] is True
