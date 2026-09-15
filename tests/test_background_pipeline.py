import asyncio

from wavecast.intelligence.background import BackgroundIntelligencePipeline
from wavecast.intelligence.curation import CuratorService
from wavecast.intelligence.fast_start import FastPathResult
from wavecast.intelligence.models import FastResearchInput, FastStartPlan, NarrationScript
from wavecast.intelligence.planning import PlanningSession
from wavecast.intelligence.research import BackgroundResearchService, FastResearchService
from wavecast.intelligence.trace import GenerationTrace
from wavecast.intelligence.writer import WriterService

from tests.test_fast_path import SearchFixture
from tests.test_intelligence_services import StructuredFixture, skeleton


def request() -> FastResearchInput:
    return FastResearchInput(
        topic="topic", anchor_tracks=["Anchor - Track"], desired_duration_seconds=900
    )


def fast_result() -> FastPathResult:
    fast = FastStartPlan(
        anchor_understanding=["anchor"],
        immediate_taste_hypotheses=[],
        next_candidates=[],
        first_narration=NarrationScript(text="start", intended_duration_seconds=5),
    )
    research = asyncio.run(
        FastResearchService(
            discovery=SearchFixture(), research=SearchFixture(), deadline_seconds=0.2
        ).run(request())
    )
    return FastPathResult(
        research=research,
        plan=fast,
        trace=GenerationTrace(request_id="fast"),
        elapsed_ms=1,
    )


def test_background_pipeline_stops_before_paid_work_when_cancelled() -> None:
    called = False

    class NeverSearch(SearchFixture):
        async def search(self, query: str, *, limit: int = 5, stage: str | None = None):
            nonlocal called
            called = True
            return await super().search(query, limit=limit, stage=stage)

    cancel = asyncio.Event()
    cancel.set()
    service = BackgroundIntelligencePipeline(
        research=BackgroundResearchService(
            discovery=NeverSearch(), research=NeverSearch(), deadline_seconds=0.2
        ),
        curator=CuratorService(StructuredFixture(skeleton())),
        writer=WriterService(StructuredFixture(skeleton().chapters[0].model_copy(update={"narration_goal": "x"}))),
    )

    result = asyncio.run(
        service.run(
            request(),
            fast_result(),
            cancel_event=cancel,
            trace=GenerationTrace(request_id="background"),
            planning=PlanningSession(),
        )
    )

    assert result is None
    assert not called
