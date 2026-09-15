import pytest
from wavecast.models.episode import (
    CoverParams,
    EpisodeSeed,
    EpisodeState,
    MusicSegment,
    NarrationSegment,
    SegmentState,
)
from wavecast.orchestration.episode import (
    EpisodeOrchestrator,
    EpisodeRuntimeError,
    InMemoryEpisodeRepository,
)


@pytest.fixture
def seed() -> EpisodeSeed:
    return EpisodeSeed(
        id="seed-1",
        title="Test program",
        topic="Test topic",
        short_description="A test promise",
        estimated_duration_seconds=300,
        opening_track_ref="mock:opening",
        opening_track_title="Immediate opening",
        opening_track_artist="Test Artist",
        cover=CoverParams(family="editorial", seed=1, palette=("#000", "#fff")),
    )


@pytest.fixture
def runtime() -> EpisodeOrchestrator:
    return EpisodeOrchestrator(InMemoryEpisodeRepository())


def test_opening_track_is_ready_immediately_and_future_advances_one_segment(
    runtime: EpisodeOrchestrator, seed: EpisodeSeed
) -> None:
    episode = runtime.start(seed)
    assert episode.state is EpisodeState.STREAMING
    assert episode.generated_frontier_seconds == 22
    assert episode.ordered_segments[0].is_audio_ready
    assert episode.ordered_segments[1].state is SegmentState.PLANNED

    updated = runtime.ensure_buffer(episode.id)
    assert updated.generated_frontier_seconds > 32
    assert updated.ordered_segments[1].state is SegmentState.AUDIO_READY
    assert updated.ordered_segments[5].state is SegmentState.PLANNED


def test_timeline_serializes_explicit_playable_audio_segment_fields(
    runtime: EpisodeOrchestrator, seed: EpisodeSeed
) -> None:
    episode = runtime.start(seed)
    opening = episode.segment("segment-opening")
    narration = episode.segment("segment-narration-1")

    assert isinstance(opening, MusicSegment)
    assert isinstance(narration, NarrationSegment)
    opening_payload = opening.model_dump(mode="json")
    assert opening_payload["audio_source_url"].startswith("/api/audio/mock/music/")
    assert opening_payload["duration_seconds"] == 22
    assert narration.model_dump(mode="json")["audio_source_url"] is None


def test_browser_completion_transitions_segments_without_server_clock(
    runtime: EpisodeOrchestrator, seed: EpisodeSeed
) -> None:
    episode = runtime.start(seed)
    runtime.ensure_buffer(episode.id, target_chapters=1)
    runtime.checkpoint_playback(episode.id, 7)

    completed = runtime.complete_current_segment(episode.id)

    assert completed.segment("segment-opening").state is SegmentState.PLAYED
    assert completed.current_segment_id == "segment-narration-1"
    assert completed.playback_position_seconds == 22
    assert completed.is_playing is True


def test_seek_cannot_cross_generated_frontier(
    runtime: EpisodeOrchestrator, seed: EpisodeSeed
) -> None:
    episode = runtime.start(seed)
    runtime.seek(episode.id, 10)
    assert runtime.get(episode.id).playback_position_seconds == 10

    with pytest.raises(EpisodeRuntimeError, match="generated frontier"):
        runtime.seek(episode.id, 23)


def test_replan_preserves_committed_content(
    runtime: EpisodeOrchestrator, seed: EpisodeSeed
) -> None:
    episode = runtime.start(seed)
    runtime.commit_segment(episode.id, "segment-opening")
    runtime.replace_speculative_music(episode.id, "A new future route")

    updated = runtime.get(episode.id)
    assert updated.segment("segment-opening").title == "Immediate opening"
    assert updated.segment("segment-bridge").title == "A new future route"
    assert updated.segment("segment-opening").is_committed


def test_next_uses_known_music_when_narration_is_not_ready(
    runtime: EpisodeOrchestrator, seed: EpisodeSeed
) -> None:
    episode = runtime.start(seed)
    updated = runtime.next_playable(episode.id)
    assert updated.current_segment_id == "segment-bridge"
    assert updated.segment("segment-bridge").is_committed
    assert updated.segment("segment-narration-1").state is SegmentState.SKIPPED


def test_exit_cancels_future_progress_and_resume_restarts_it(
    runtime: EpisodeOrchestrator, seed: EpisodeSeed
) -> None:
    episode = runtime.start(seed)
    runtime.leave(episode.id)
    with pytest.raises(EpisodeRuntimeError, match="session is inactive"):
        runtime.ensure_buffer(episode.id)
    assert runtime.get(episode.id).generated_frontier_seconds == 22

    runtime.resume(episode.id)
    advanced = runtime.ensure_buffer(episode.id)
    assert advanced.generated_frontier_seconds > 22


def test_full_materialization_makes_a_fixed_complete_timeline(
    runtime: EpisodeOrchestrator, seed: EpisodeSeed
) -> None:
    episode = runtime.start(seed)
    materialized = runtime.materialize_all(episode.id)
    assert materialized.state is EpisodeState.MATERIALIZED
    assert materialized.generated_frontier_seconds == materialized.estimated_total_seconds

    after_advance = runtime.ensure_buffer(episode.id)
    assert after_advance.model_dump() == materialized.model_dump()
