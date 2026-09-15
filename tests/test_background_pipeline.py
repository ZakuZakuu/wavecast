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


def test_background_writer_targets_first_speculative_chapter_after_committed_prefix() -> None:
    committed = skeleton().chapters[0]
    speculative = skeleton().chapters[1]
    script = NarrationScript(text="future narration", intended_duration_seconds=8)

    class CuratorThenWriter:
        def __init__(self) -> None:
            self.outputs = [skeleton(), script]
            self.prompts: list[str] = []

        async def structured(
            self, prompt: str, _output_type: type[object], **_kwargs: object
        ) -> object:
            self.prompts.append(prompt)
            return self.outputs.pop(0)

    llm = CuratorThenWriter()
    planning = PlanningSession(committed_chapters=[committed])
    service = BackgroundIntelligencePipeline(
        research=BackgroundResearchService(
            discovery=SearchFixture(), research=SearchFixture(), deadline_seconds=0.2
        ),
        curator=CuratorService(llm),
        writer=WriterService(llm),
    )

    result = asyncio.run(
        service.run(
            request(),
            fast_result(),
            cancel_event=asyncio.Event(),
            trace=GenerationTrace(request_id="background-speculative"),
            planning=planning,
        )
    )

    assert result is not None
    assert result.future_script == script
    assert planning.committed_chapters == [committed]
    assert planning.speculative_chapters == [speculative]
    assert '"title":"Discovery"' in llm.prompts[1]
    assert '"title":"Close"' not in llm.prompts[1]


def test_background_pipeline_does_not_write_when_all_chapters_are_committed() -> None:
    class CountingLLM:
        def __init__(self) -> None:
            self.calls = 0

        async def structured(
            self, _prompt: str, _output_type: type[object], **_kwargs: object
        ) -> object:
            self.calls += 1
            return skeleton()

    llm = CountingLLM()
    chapters = skeleton().chapters
    planning = PlanningSession(committed_chapters=list(chapters))
    service = BackgroundIntelligencePipeline(
        research=BackgroundResearchService(
            discovery=SearchFixture(), research=SearchFixture(), deadline_seconds=0.2
        ),
        curator=CuratorService(llm),
        writer=WriterService(llm),
    )

    result = asyncio.run(
        service.run(
            request(),
            fast_result(),
            cancel_event=asyncio.Event(),
            trace=GenerationTrace(request_id="background-no-speculative"),
            planning=planning,
        )
    )

    assert result is not None
    assert result.future_script is None
    assert llm.calls == 1
