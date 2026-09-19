import asyncio
import json

import pytest
from pydantic import ValidationError
from wavecast.intelligence.models import (
    ChapterPlan,
    EditorialConnection,
    EditorialRelationType,
    Evidence,
    FastStartPlan,
    NarrationScript,
    NarrativeRole,
    NoveltyDistance,
    OutputLanguage,
    ProgramSkeleton,
    ResolvedTrack,
    ResolvedTrackCandidate,
    TasteHypothesis,
    TrackCandidate,
    TrackProposal,
    resolve_output_language,
)
from wavecast.intelligence.resolution import (
    UnresolvedTrackError,
    music_segment_from_track,
    resolve_track_candidate,
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


def test_narrative_chapter_can_have_no_track_and_language_auto_uses_topic() -> None:
    chapter = ChapterPlan(
        index=0,
        track=None,
        narrative_role=NarrativeRole.BRIDGE,
        reason="explain the context before the next song",
        narration_goal="tell the story",
    )

    assert chapter.track is None
    assert resolve_output_language(OutputLanguage.AUTO, "藤井风的音乐背景") is OutputLanguage.ZH_CN
    assert resolve_output_language(OutputLanguage.EN_US, "藤井风的音乐背景") is OutputLanguage.EN_US


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


def test_proposal_rejects_catalog_identity_fields() -> None:
    with pytest.raises(ValidationError):
        TrackProposal(
            artist="Fake Artist",
            title="Fake Song",
            track_ref="mock:opening",
            confidence=0.5,
        )


def test_llm_facing_schemas_do_not_expose_catalog_identity_fields() -> None:
    proposal = TrackProposal(artist="Artist", title="Title", confidence=0.5)
    skeleton = ProgramSkeleton(
        thesis="An arc",
        estimated_duration_seconds=120,
        chapters=[
            ChapterPlan(
                index=0,
                track=proposal,
                narrative_role=NarrativeRole.ANCHOR,
                reason="anchor",
                novelty_distance=NoveltyDistance.VERY_CLOSE,
                narration_goal="introduce",
            )
        ],
    )
    fast = FastStartPlan(
        anchor_understanding=["anchor"],
        immediate_taste_hypotheses=[],
        next_candidates=[proposal],
        first_narration=NarrationScript(text="Start here.", intended_duration_seconds=5),
    )

    for schema in (fast.model_json_schema(), skeleton.model_json_schema()):
        serialized = json.dumps(schema)
        assert "track_ref" not in serialized
        assert "canonical_artist" not in serialized
        assert "canonical_title" not in serialized


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


def test_timeline_boundary_accepts_resolver_output_but_not_a_proposal() -> None:
    proposal = TrackProposal(artist="Mira Fields", title="Neon First Light", confidence=0.8)
    resolved = asyncio.run(resolve_track_candidate(FakeMusicProvider(), proposal))
    assert isinstance(resolved, ResolvedTrackCandidate)

    segment = music_segment_from_track(
        resolved,
        chapter_id="chapter-1",
        order=0,
        planned_duration_seconds=22,
    )
    assert segment.track_ref == "mock:opening"

    with pytest.raises(UnresolvedTrackError):
        music_segment_from_track(proposal, chapter_id="chapter-1", order=0)


def test_resolved_track_is_accepted_without_a_candidate_wrapper() -> None:
    segment = music_segment_from_track(
        ResolvedTrack(
            track_ref="mock:opening",
            canonical_artist="Mira Fields",
            canonical_title="Neon First Light",
        ),
        chapter_id="chapter-1",
        order=0,
        planned_duration_seconds=22,
    )

    assert segment.track_ref == "mock:opening"


def test_editorial_connection_is_typed_and_serializable() -> None:
    connection = EditorialConnection(
        relation_type=EditorialRelationType.SCENE_OR_LINEAGE,
        musical_dimensions=["vocal phrasing", "rhythmic pocket"],
        rationale="The later track extends the same vocal pocket through a related scene.",
        evidence_ids=["e1"],
    )
    chapter = ChapterPlan(
        index=1,
        track=TrackProposal(artist="Current", title="Track", confidence=0.8),
        connection_from_previous_track=connection,
        narrative_role=NarrativeRole.BRIDGE,
        reason="move through a related scene",
        narration_goal="explain the bridge",
    )

    payload = chapter.model_dump(mode="json")
    assert payload["connection_from_previous_track"]["relation_type"] == "scene_or_lineage"
    assert payload["connection_from_previous_track"]["musical_dimensions"] == [
        "vocal phrasing",
        "rhythmic pocket",
    ]
