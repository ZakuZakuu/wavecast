import asyncio

import pytest
from wavecast.intelligence.curation import CuratorService
from wavecast.intelligence.models import (
    ChapterPlan,
    ClaimSupport,
    ClaimType,
    EditorialConnection,
    EditorialRelationType,
    Evidence,
    FastStartPlan,
    NarrationScript,
    NarrativeRole,
    NoveltyDistance,
    ProgramSkeleton,
    ResearchBundle,
    ResearchPlan,
    ResolvedTrackCandidate,
    TrackCandidate,
)
from wavecast.intelligence.planning import PlanningSession
from wavecast.intelligence.writer import WriterService
from wavecast.providers.profiles import InferenceProfile


class StructuredFixture:
    def __init__(self, output: object) -> None:
        self.output = output
        self.prompts: list[str] = []
        self.calls: list[dict[str, object]] = []

    async def structured(self, prompt: str, _output_type: type[object], **kwargs: object) -> object:
        self.prompts.append(prompt)
        self.calls.append(kwargs)
        return self.output


def candidate(title: str, distance: NoveltyDistance) -> TrackCandidate:
    return TrackCandidate(
        artist="Artist",
        title=title,
        reasons=["because"],
        similarity_dimensions=["groove"],
        evidence_ids=["e1"],
        confidence=0.8,
        novelty_distance=distance,
    )


def skeleton() -> ProgramSkeleton:
    return ProgramSkeleton(
        thesis="An arc",
        estimated_duration_seconds=1200,
        chapters=[
            ChapterPlan(
                index=0,
                track=candidate("Close", NoveltyDistance.CLOSE),
                narrative_role=NarrativeRole.VALIDATION,
                reason="stay near",
                novelty_distance=NoveltyDistance.CLOSE,
                narration_goal="explain texture",
                evidence_ids=["e1"],
            ),
            ChapterPlan(
                index=1,
                track=candidate("Discovery", NoveltyDistance.DISCOVERY),
                narrative_role=NarrativeRole.DISCOVERY,
                reason="open outward",
                novelty_distance=NoveltyDistance.DISCOVERY,
                narration_goal="connect groove",
                evidence_ids=["e1"],
            ),
        ],
    )


def test_curator_preserves_narrative_distance_curve_without_search_dependency() -> None:
    fixture = StructuredFixture(skeleton())
    service = CuratorService(fixture)
    bundle = ResearchBundle(
        anchors=["Anchor"],
        taste_hypotheses=[],
        evidence=[
            Evidence(
                id="e1",
                claim_or_excerpt="fixture evidence",
                source_url="https://example.test/e1",
                source_provider="fixture",
                confidence=0.8,
                query="fixture",
            )
        ],
        candidates=[candidate("Bundle candidate", NoveltyDistance.CLOSE)],
        research_plan=ResearchPlan(central_question="Why this route?"),
    )
    fast = FastStartPlan(
        anchor_understanding=["anchor"],
        immediate_taste_hypotheses=[],
        next_candidates=[],
        first_narration=NarrationScript(text="start", intended_duration_seconds=5),
    )

    committed = skeleton().chapters[0].model_copy(
        update={
            "claim_support": [
                ClaimSupport(
                    claim_type=ClaimType.FACT,
                    claim="supported fixture claim",
                    evidence_ids=["e1"],
                )
            ],
            "connection_from_previous_track": EditorialConnection(
                relation_type=EditorialRelationType.SHARED_RHYTHMIC_POCKET,
                musical_dimensions=["groove"],
                rationale="fixture connection",
                evidence_ids=["e1"],
            ),
        }
    )
    result = asyncio.run(
        service.curate(
            bundle,
            fast,
            desired_duration_seconds=1200,
            committed_chapters=[committed],
        )
    )

    assert [chapter.novelty_distance for chapter in result.chapters] == [
        NoveltyDistance.CLOSE,
        NoveltyDistance.DISCOVERY,
    ]
    assert [chapter.index for chapter in result.chapters] == [0, 1]
    assert all(not isinstance(chapter.track, ResolvedTrackCandidate) for chapter in result.chapters)
    assert not hasattr(service, "discovery")
    assert fixture.calls[0]["profile"] is InferenceProfile.CURATOR
    assert fixture.calls[0]["stage"] == "curator"
    assert "Playback order is exactly chapter order" in fixture.prompts[0]
    assert "very_close keeps the same core sonic identity" in fixture.prompts[0]
    assert "new artists or scenes" in fixture.prompts[0]
    assert "prefer a 3-5 track-bearing listening arc" in fixture.prompts[0]
    assert "not alternate or unused backup proposals" in fixture.prompts[0]
    assert "max_tracks is at least 3" in fixture.prompts[0]
    assert "first_narration" not in fixture.prompts[0]
    assert fixture.prompts[0].count('"central_question"') == 1
    assert "Bundle candidate" in fixture.prompts[0]
    assert '"evidence"' in fixture.prompts[0]
    assert '"claim_support"' in fixture.prompts[0]
    assert '"connection_from_previous_track"' in fixture.prompts[0]


def test_curator_normalizes_backward_novelty_curve() -> None:
    invalid = skeleton().model_copy(
        update={
            "chapters": [
                skeleton().chapters[0].model_copy(
                    update={"novelty_distance": NoveltyDistance.SURPRISE}
                ),
                skeleton().chapters[1].model_copy(
                    update={"novelty_distance": NoveltyDistance.BRIDGE}
                ),
            ]
        }
    )
    fixture = StructuredFixture(invalid)
    service = CuratorService(fixture)
    bundle = ResearchBundle(
        anchors=["Anchor"],
        taste_hypotheses=[],
        evidence=[
            Evidence(
                id="e1",
                claim_or_excerpt="fixture evidence",
                source_url="https://example.test/e1",
                source_provider="fixture",
                confidence=0.8,
                query="fixture",
            )
        ],
        candidates=[],
    )
    fast = FastStartPlan(
        anchor_understanding=["anchor"],
        immediate_taste_hypotheses=[],
        next_candidates=[],
        first_narration=NarrationScript(text="start", intended_duration_seconds=5),
    )

    result = asyncio.run(service.curate(bundle, fast, desired_duration_seconds=1200))

    assert [chapter.novelty_distance for chapter in result.chapters] == [
        NoveltyDistance.SURPRISE,
        NoveltyDistance.SURPRISE,
    ]
    assert result.chapters[1].track is not None
    assert result.chapters[1].track.novelty_distance is NoveltyDistance.SURPRISE


def test_curator_drops_unknown_chapter_evidence_without_claim_support() -> None:
    invalid = skeleton().model_copy(
        update={
            "chapters": [
                skeleton().chapters[0].model_copy(
                    update={"evidence_ids": ["ghost"], "claim_support": []}
                )
            ]
        }
    )
    fixture = StructuredFixture(invalid)
    service = CuratorService(fixture)
    bundle = ResearchBundle(
        anchors=["Anchor"],
        taste_hypotheses=[],
        evidence=[
            Evidence(
                id="e1",
                claim_or_excerpt="fixture evidence",
                source_url="https://example.test/e1",
                source_provider="fixture",
                confidence=0.8,
                query="fixture",
            )
        ],
        candidates=[],
    )
    fast = FastStartPlan(
        anchor_understanding=["anchor"],
        immediate_taste_hypotheses=[],
        next_candidates=[],
        first_narration=NarrationScript(text="start", intended_duration_seconds=5),
    )

    result = asyncio.run(service.curate(bundle, fast, desired_duration_seconds=1200))

    assert result.chapters[0].evidence_ids == []


def test_writer_receives_only_evidence_scoped_to_chapter() -> None:
    script = NarrationScript(text="Scoped", intended_duration_seconds=6)
    fixture = StructuredFixture(script)
    service = WriterService(fixture)
    chapter = skeleton().chapters[0]
    evidence = [
        Evidence(
            id="e1",
            claim_or_excerpt="allowed",
            source_url="https://example.test/allowed",
            source_provider="fixture",
            confidence=0.8,
            query="q",
        ),
        Evidence(
            id="e2",
            claim_or_excerpt="not allowed",
            source_url="https://example.test/other",
            source_provider="fixture",
            confidence=0.8,
            query="q",
        ),
    ]

    result = asyncio.run(service.write(chapter, evidence))

    assert result.text == "Scoped"
    assert "allowed" in fixture.prompts[0]
    assert "not allowed" not in fixture.prompts[0]


def test_committed_planning_chapter_cannot_be_rewritten() -> None:
    session = PlanningSession(committed_chapters=[skeleton().chapters[0]])
    changed = skeleton().chapters[0].model_copy(update={"reason": "rewritten"})

    try:
        session.apply_skeleton(ProgramSkeleton.model_validate(skeleton().model_copy(update={"chapters": [changed]})))
    except ValueError as error:
        assert "committed" in str(error)
    else:
        raise AssertionError("committed chapter was rewritten")


def test_curator_and_planning_preserve_committed_prefix_exactly() -> None:
    committed = skeleton().chapters[0]
    service = CuratorService(StructuredFixture(skeleton()))
    bundle = ResearchBundle(
        anchors=["Anchor"],
        taste_hypotheses=[],
        evidence=[
            Evidence(
                id="e1",
                claim_or_excerpt="fixture evidence",
                source_url="https://example.test/e1",
                source_provider="fixture",
                confidence=0.8,
                query="fixture",
            )
        ],
        candidates=[],
    )
    fast = FastStartPlan(
        anchor_understanding=["anchor"],
        immediate_taste_hypotheses=[],
        next_candidates=[],
        first_narration=NarrationScript(text="start", intended_duration_seconds=5),
    )
    session = PlanningSession(committed_chapters=[committed])

    result = asyncio.run(
        service.curate(
            bundle,
            fast,
            desired_duration_seconds=1200,
            committed_chapters=[committed],
        )
    )
    session.apply_skeleton(result)

    assert result.chapters[0] == committed
    assert session.committed_chapters == [committed]
