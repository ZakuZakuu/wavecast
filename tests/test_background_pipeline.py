import asyncio

from wavecast.intelligence.background import BackgroundIntelligencePipeline
from wavecast.intelligence.curation import CuratorService
from wavecast.intelligence.fast_start import FastPathResult
from wavecast.intelligence.models import (
    FastResearchInput,
    FastStartPlan,
    NarrationScript,
    PlannedResearchQuery,
    ResearchFacet,
    ResearchPlan,
    SearchIntent,
)
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


def curator_fixture_skeleton_without_evidence():
    current = skeleton()
    return current.model_copy(
        update={
            "chapters": [
                chapter.model_copy(update={"evidence_ids": []})
                for chapter in current.chapters
            ]
        }
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


def test_background_pipeline_passes_adaptive_plan_to_research_service() -> None:
    class RecordingSearch(SearchFixture):
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def search(self, query: str, *, limit: int = 5, stage: str | None = None):
            self.calls.append(query)
            return await super().search(query, limit=limit, stage=stage)

    exa = RecordingSearch()
    tavily = RecordingSearch()
    custom_plan = ResearchPlan(
        central_question="How does this specific question work?",
        facets=[
            ResearchFacet(
                id="fixture",
                label="Fixture context",
                question="What evidence answers the fixture question?",
                priority=80,
            )
        ],
        background_queries=[
            PlannedResearchQuery(
                query="distinctive adaptive query",
                intent=SearchIntent.DISCOVERY,
                facet_ids=["fixture"],
                rationale="fixture-only routing assertion",
            )
        ],
    )
    fast = fast_result()
    fast.plan = fast.plan.model_copy(update={"research_plan": custom_plan})
    writer_output = StructuredFixture(NarrationScript(text="future script", intended_duration_seconds=5))
    curator_output = StructuredFixture(curator_fixture_skeleton_without_evidence())
    pipeline = BackgroundIntelligencePipeline(
        research=BackgroundResearchService(
            discovery=exa,
            research=tavily,
            deadline_seconds=0.2,
        ),
        curator=CuratorService(curator_output),
        writer=WriterService(writer_output),
    )

    result = asyncio.run(
        pipeline.run(
            request(),
            fast,
            cancel_event=asyncio.Event(),
            trace=GenerationTrace(request_id="adaptive-pipeline"),
        )
    )

    assert result is not None
    assert exa.calls == ["distinctive adaptive query"]
    assert tavily.calls == []
    assert all("related context and perspectives" not in query for query in exa.calls)


def test_background_writer_targets_first_speculative_chapter_after_committed_prefix() -> None:
    fixture_skeleton = curator_fixture_skeleton_without_evidence()
    committed = fixture_skeleton.chapters[0]
    assert fixture_skeleton.chapters[1].track is not None
    speculative = fixture_skeleton.chapters[1].model_copy(
        update={
            "track": fixture_skeleton.chapters[1].track.model_copy(
                update={"evidence_ids": []}
            )
        }
    )
    script = NarrationScript(text="future narration", intended_duration_seconds=8)

    class CuratorThenWriter:
        def __init__(self) -> None:
            self.outputs = [curator_fixture_skeleton_without_evidence(), script]
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
            return curator_fixture_skeleton_without_evidence()

    llm = CountingLLM()
    chapters = curator_fixture_skeleton_without_evidence().chapters
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
