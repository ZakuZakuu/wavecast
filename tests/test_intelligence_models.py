from wavecast.intelligence.models import (
    Evidence,
    FastStartPlan,
    NarrationScript,
    NoveltyDistance,
    TasteHypothesis,
    TrackCandidate,
)
from wavecast.intelligence.trace import GenerationTrace


def test_fast_start_plan_keeps_evidence_and_novelty_typed() -> None:
    candidate = TrackCandidate(
        artist="Example Artist",
        title="Example Track",
        reasons=["shared rhythmic feel"],
        similarity_dimensions=["groove"],
        evidence_ids=["e1"],
        confidence=0.8,
        novelty_distance=NoveltyDistance.BRIDGE,
    )
    plan = FastStartPlan(
        anchor_understanding=["layered groove"],
        immediate_taste_hypotheses=[
            TasteHypothesis(
                dimension="groove", interpretation="syncopated and warm", confidence=0.7
            )
        ],
        next_candidates=[candidate],
        selected_next_track=candidate,
        first_narration=NarrationScript(
            text="We can follow the groove outward.", intended_duration_seconds=8
        ),
        uncertainties=["catalog availability"],
    )

    assert plan.selected_next_track is not None
    assert plan.selected_next_track.novelty_distance is NoveltyDistance.BRIDGE


def test_generation_trace_derives_time_to_first_script() -> None:
    trace = GenerationTrace(request_id="request-1")
    trace.mark("fast_research_started")
    trace.mark("fast_plan_ready", candidate_count=2)

    assert trace.time_to_first_script_ms is not None
    assert trace.time_to_first_script_ms >= 0
    assert not trace.fallback_used


def test_evidence_requires_normalized_source_fields() -> None:
    evidence = Evidence(
        id="e1",
        claim_or_excerpt="A short normalized excerpt",
        source_url="https://example.test/source",
        source_provider="exa",
        confidence=0.5,
        query="example",
    )

    assert evidence.model_dump()["source_provider"] == "exa"
