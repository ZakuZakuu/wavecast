import asyncio

from wavecast.intelligence.fast_start import FastPathCoordinator, FastStartPlanner
from wavecast.intelligence.models import (
    FastResearchInput,
    FastStartPlan,
    NarrationScript,
)
from wavecast.intelligence.research import FastResearchService
from wavecast.providers.contracts import SearchResult
from wavecast.providers.profiles import InferenceProfile, StructuredTransport


class SearchFixture:
    async def search(self, query: str, *, limit: int = 5) -> list[SearchResult]:
        del limit
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
    assert result.plan.first_narration.text.startswith("先从 Anchor - Opening")
    assert "Fixture Artist" not in result.plan.first_narration.text
