import asyncio

from wavecast.intelligence.models import (
    Evidence,
    FastStartPlan,
    NarrationScript,
    NoveltyDistance,
    TasteHypothesis,
    TrackCandidate,
    TrackProposal,
)
from wavecast.intelligence.resolution import (
    UnresolvedTrackError,
    music_segment_from_track,
    resolve_track_proposal,
)
from wavecast.intelligence.trace import GenerationTrace
from wavecast.providers.fakes import FakeMusicProvider


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
    trace.mark("first_script_ready", fallback=False, candidate_count=2)

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


def test_known_mock_track_resolves_to_a_stable_catalog_entity() -> None:
    proposal = TrackProposal(
        artist="Mira Fields",
        title="Neon First Light",
        confidence=0.8,
        reasons=["known opening anchor"],
        similarity_dimensions=["groove"],
    )

    resolved = asyncio.run(resolve_track_proposal(FakeMusicProvider(), proposal))

    assert resolved is not None
    assert resolved.track_ref == "mock:opening"
    assert resolved.canonical_artist == "Mira Fields"
    assert resolved.canonical_title == "Neon First Light"


def test_event_page_like_proposal_stays_unresolved_without_title_heuristics() -> None:
    proposal = TrackProposal(
        artist="Festival Listing",
        title="Live at an Asheville Music Hall 8-9-2026",
        confidence=0.4,
    )

    resolved = asyncio.run(resolve_track_proposal(FakeMusicProvider(), proposal))

    assert resolved is None


def test_catalog_reference_without_canonical_identity_is_not_resolved() -> None:
    candidate = TrackCandidate(
        artist="LLM Artist",
        title="LLM Title",
        track_ref="unverified:ref",
        confidence=0.5,
    )

    assert candidate.resolution_status == "unresolved"
    assert not candidate.is_resolved


def test_unresolved_proposal_cannot_become_a_playable_music_segment() -> None:
    proposal = TrackProposal(artist="Unknown", title="Uncatalogued Track", confidence=0.2)

    try:
        music_segment_from_track(proposal, chapter_id="chapter-1", order=0)
    except UnresolvedTrackError:
        pass
    else:
        raise AssertionError("an unresolved proposal became a playable segment")


def test_resolved_track_is_the_only_track_identity_accepted_by_timeline_boundary() -> None:
    proposal = TrackProposal(artist="Mira Fields", title="Neon First Light", confidence=0.8)
    resolved = asyncio.run(resolve_track_proposal(FakeMusicProvider(), proposal))
    assert resolved is not None

    segment = music_segment_from_track(
        resolved,
        chapter_id="chapter-1",
        order=0,
        planned_duration_seconds=22,
    )

    assert segment.track_ref == "mock:opening"
    assert segment.title == "Neon First Light"
    assert not segment.is_audio_ready
