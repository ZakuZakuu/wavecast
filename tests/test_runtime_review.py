from datetime import UTC, datetime, timedelta

import pytest
from wavecast.models.episode import CoverParams, EpisodeSeed, SegmentState
from wavecast.orchestration.episode import (
    EpisodeOrchestrator,
    EpisodeRuntimeError,
    InMemoryEpisodeRepository,
)


def make_seed() -> EpisodeSeed:
    return EpisodeSeed(
        id="runtime-review-seed",
        title="Runtime review fixture",
        topic="Playback semantics",
        short_description="A deterministic runtime fixture",
        estimated_duration_seconds=30 * 60,
        opening_track_ref="mock:opening",
        opening_track_title="Immediate opening",
        opening_track_artist="Test Artist",
        cover=CoverParams(family="editorial", seed=1, palette=("#000", "#fff")),
    )


def make_runtime() -> EpisodeOrchestrator:
    return EpisodeOrchestrator(InMemoryEpisodeRepository())


def test_playback_clock_automatically_advances_and_marks_completed_segments_played() -> None:
    runtime = make_runtime()
    episode = runtime.start(make_seed())
    runtime.ensure_buffer(episode.id)

    advanced = runtime.tick(episode.id, elapsed_seconds=22)

    assert advanced.segment("segment-opening").state is SegmentState.PLAYED
    assert advanced.current_segment_id == "segment-narration-1"
    assert advanced.playback_position_seconds == 22


def test_skip_removes_unready_narration_and_keeps_generated_frontier_continuous() -> None:
    runtime = make_runtime()
    episode = runtime.start(make_seed())

    skipped = runtime.next_playable(episode.id)
    active_before_current = [
        segment
        for segment in skipped.ordered_segments
        if segment.order <= skipped.segment(skipped.current_segment_id).order
        and segment.state is not SegmentState.SKIPPED
    ]
    assert skipped.segment("segment-narration-1").state is SegmentState.SKIPPED
    assert all(segment.is_audio_ready for segment in active_before_current)
    assert skipped.playback_position_seconds <= skipped.generated_frontier_seconds


def test_start_or_resume_returns_the_existing_episode_for_a_seed() -> None:
    runtime = make_runtime()
    first = runtime.start_or_resume(make_seed())
    runtime.leave(first.id)

    resumed = runtime.start_or_resume(make_seed())

    assert resumed.id == first.id
    assert resumed.is_listener_active is True


def test_ensure_buffer_stops_after_two_ready_future_chapters() -> None:
    runtime = make_runtime()
    episode = runtime.start(make_seed())

    buffered = runtime.ensure_buffer(episode.id, target_chapters=2)
    later_segment = buffered.segment("segment-narration-3")
    snapshot = [segment.model_dump() for segment in buffered.segments]
    unchanged = runtime.ensure_buffer(episode.id, target_chapters=2)

    assert later_segment.state is SegmentState.PLANNED
    assert [segment.model_dump() for segment in unchanged.segments] == snapshot


def test_program_promise_duration_is_not_the_current_mock_timeline_duration() -> None:
    runtime = make_runtime()
    episode = runtime.start(make_seed())

    assert episode.program_estimated_duration_seconds == 30 * 60
    assert episode.timeline_duration_seconds < episode.program_estimated_duration_seconds


def test_heartbeat_ttl_stops_a_stale_listener_before_more_generation() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    runtime = EpisodeOrchestrator(InMemoryEpisodeRepository(), now=lambda: now)
    episode = runtime.start(make_seed())
    now += timedelta(seconds=31)

    runtime.expire_stale_sessions()

    assert runtime.get(episode.id).is_listener_active is False
    with pytest.raises(EpisodeRuntimeError, match="session is inactive"):
        runtime.ensure_buffer(episode.id)
