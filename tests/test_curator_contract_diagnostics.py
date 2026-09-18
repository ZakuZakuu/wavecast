import asyncio

from wavecast.intelligence.curation import (
    CuratorContractError,
    CuratorService,
    _validate_curator_contract,
)
from wavecast.intelligence.models import (
    ChapterPlan,
    ClaimSupport,
    ClaimType,
    Evidence,
    FastStartPlan,
    NarrationScript,
    NarrativeRole,
    NoveltyDistance,
    ProgramSkeleton,
    ResearchBundle,
    TrackProposal,
)
from wavecast.intelligence.trace import GenerationTrace
from wavecast.intelligence.writer import WriterService


class CuratorFixture:
    def __init__(self, output: ProgramSkeleton) -> None:
        self.output = output

    async def structured(self, _prompt: str, _output_type: type[object], **_kwargs: object) -> object:
        return self.output


class WriterFixture:
    def __init__(self) -> None:
        self.prompt = ""

    async def structured(self, prompt: str, _output_type: type[object], **_kwargs: object) -> object:
        self.prompt = prompt
        return NarrationScript(text="A careful transition.", intended_duration_seconds=5)


def evidence(evidence_id: str) -> Evidence:
    return Evidence(
        id=evidence_id,
        claim_or_excerpt=f"Evidence {evidence_id}",
        source_url=f"https://example.test/{evidence_id}",
        source_provider="fixture",
        confidence=0.8,
        query="fixture",
    )


def fast_plan() -> FastStartPlan:
    return FastStartPlan(
        anchor_understanding=[],
        immediate_taste_hypotheses=[],
        next_candidates=[],
        first_narration=NarrationScript(text="start", intended_duration_seconds=5),
    )


def test_curator_normalizes_unknown_references_and_records_safe_diagnostics() -> None:
    skeleton = ProgramSkeleton(
        thesis="fixture",
        estimated_duration_seconds=60,
        chapters=[
            ChapterPlan(
                index=0,
                track=TrackProposal(
                    artist="Artist",
                    title="Track",
                    evidence_ids=["ghost", "e2", "e2"],
                    confidence=0.8,
                ),
                narrative_role=NarrativeRole.ANCHOR,
                reason="fixture",
                novelty_distance=NoveltyDistance.CLOSE,
                evidence_ids=["e1", "ghost", "e1"],
                claim_support=[
                    ClaimSupport(
                        claim_type=ClaimType.FACT,
                        claim="grounded",
                        evidence_ids=["e1", "ghost", "e1"],
                    ),
                    ClaimSupport(
                        claim_type=ClaimType.INTERPRETATION,
                        claim="unsupported",
                        evidence_ids=["ghost"],
                    ),
                ],
                narration_goal="introduce",
            )
        ],
    )
    trace = GenerationTrace(request_id="fixture")
    result = asyncio.run(
        CuratorService(CuratorFixture(skeleton)).curate(
            ResearchBundle(
                anchors=[],
                taste_hypotheses=[],
                evidence=[evidence("e1"), evidence("e2")],
                candidates=[],
            ),
            fast_plan(),
            desired_duration_seconds=60,
            trace=trace,
        )
    )

    chapter = result.chapters[0]
    assert chapter.evidence_ids == ["e1"]
    assert chapter.track is not None
    assert chapter.track.evidence_ids == ["e2"]
    assert [support.evidence_ids for support in chapter.claim_support] == [["e1"]]
    diagnostics = [
        event.metadata
        for event in trace.events
        if event.name == "curator_reference_normalized"
    ]
    assert diagnostics
    assert all("prompt" not in item and "response" not in item for item in diagnostics)
    assert {item["reference_kind"] for item in diagnostics} == {
        "chapter_evidence",
        "claim_support",
        "track_evidence",
    }


def test_curator_contract_helper_remains_strict_after_normalization() -> None:
    skeleton = ProgramSkeleton(
        thesis="fixture",
        estimated_duration_seconds=60,
        chapters=[
            ChapterPlan(
                index=0,
                track=None,
                narrative_role=NarrativeRole.BRIDGE,
                reason="fixture",
                novelty_distance=NoveltyDistance.CLOSE,
                evidence_ids=["ghost"],
                narration_goal="connect",
            )
        ],
    )
    try:
        _validate_curator_contract(skeleton, ResearchBundle(
            anchors=[], taste_hypotheses=[], evidence=[evidence("e1")], candidates=[]
        ))
    except CuratorContractError as error:
        assert error.reason_code == "curator_chapter_evidence_scope_invalid"
    else:  # pragma: no cover - assertion guard
        raise AssertionError("invalid unnormalized contract was accepted")


def test_writer_empty_evidence_scope_forbids_concrete_claims() -> None:
    fixture = WriterFixture()
    chapter = ChapterPlan(
        index=0,
        track=None,
        narrative_role=NarrativeRole.BRIDGE,
        reason="transition",
        novelty_distance=None,
        evidence_ids=[],
        narration_goal="connect adjacent tracks",
    )

    asyncio.run(WriterService(fixture).write(chapter, []))

    assert "evidence scope is empty" in fixture.prompt
    assert "Do not make concrete factual, causal, date, statistical, or biographical claims" in fixture.prompt
