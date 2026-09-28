import pytest
from wavecast.models.episode import (
    GenerationMode,
    LiveEpisode,
    MusicSegment,
    NarrationSegment,
    SegmentState,
)
from wavecast.orchestration.buffer import buffer_decision
from wavecast.orchestration.episode import EpisodeOrchestrator, InMemoryEpisodeRepository


def episode(*, successor: bool = False) -> LiveEpisode:
    value = LiveEpisode(
        seed_id="seed",
        title="Radio",
        topic="Music",
        program_estimated_duration_seconds=1200,
        current_segment_id="opening",
        playback_position_seconds=60,
        segments=[
            MusicSegment(
                id="opening",
                chapter_id="one",
                order=0,
                title="Opening",
                track_ref="mock:opening",
                planned_duration_seconds=300,
                state=SegmentState.COMMITTED,
            )
        ],
    )
    if successor:
        value.segments.extend(
            [
                NarrationSegment(
                    id="optional",
                    chapter_id="two",
                    order=1,
                    title="Optional",
                    planned_duration_seconds=20,
                ),
                MusicSegment(
                    id="next",
                    chapter_id="two",
                    order=2,
                    title="Next",
                    track_ref="mock:next",
                    planned_duration_seconds=180,
                    state=SegmentState.AUDIO_READY,
                ),
            ]
        )
    return value


def test_long_opening_still_needs_successor() -> None:
    decision = buffer_decision(episode())
    assert decision.needs_generation
    assert decision.current_remaining_seconds == 240
    assert not decision.urgent


def test_short_runway_is_urgent_without_a_successor() -> None:
    value = episode()
    value.playback_position_seconds = 280
    assert buffer_decision(value).urgent


def test_optional_narration_does_not_make_healthy_music_buffer_unhealthy() -> None:
    assert not buffer_decision(episode(successor=True)).needs_generation


def test_slow_generation_triggers_earlier_refill_and_is_durable() -> None:
    value = episode(successor=True)
    value.generation_latency_seconds = 300
    restored = LiveEpisode.model_validate_json(value.model_dump_json())
    decision = buffer_decision(restored)
    assert decision.needs_generation
    assert decision.target_seconds == 480


def test_progressive_leave_and_full_have_different_lifetimes() -> None:
    value = episode()
    value.is_listener_active = False
    assert not buffer_decision(value).needs_generation
    value.generation_mode = GenerationMode.FULL
    assert buffer_decision(value).needs_generation


def test_old_snapshot_defaults_to_baseline() -> None:
    payload = episode().model_dump()
    payload.pop("generation_latency_seconds")
    assert buffer_decision(LiveEpisode.model_validate(payload)).target_seconds == 180


def test_healthy_buffer_does_not_plan_or_rewrite_segments() -> None:
    repository = InMemoryEpisodeRepository()
    value = repository.save(episode(successor=True))
    before = value.model_dump_json()
    runtime = EpisodeOrchestrator(repository)
    assert runtime.ensure_buffer(value.id).model_dump_json() == before


def test_latency_sample_is_recorded_only_when_new_audio_becomes_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    samples = iter([0.0, 120.0, 120.0])
    monkeypatch.setattr("wavecast.orchestration.episode.monotonic", lambda: next(samples))
    repository = InMemoryEpisodeRepository()
    value = repository.save(episode())
    runtime = EpisodeOrchestrator(repository)
    result = runtime.ensure_buffer(value.id)
    assert result.has_ready_successor
    assert result.generation_latency_seconds == 120
    previous = result.generation_latency_seconds
    assert runtime.ensure_buffer(value.id).generation_latency_seconds == previous


def test_healthy_buffer_still_recovers_after_browser_ended() -> None:
    repository = InMemoryEpisodeRepository()
    value = episode(successor=True)
    value.segments[0].state = SegmentState.PLAYED
    value.playback_position_seconds = 300
    value.is_playing = False
    repository.save(value)
    restored = EpisodeOrchestrator(repository).ensure_buffer(value.id, target_ahead_seconds=180)
    assert restored.current_segment_id == "next"
    assert restored.is_playing
    assert restored.segments[0].state is SegmentState.PLAYED


def test_chapter_cap_prevents_unproductive_refill_requests() -> None:
    value = episode(successor=True)
    value.generation_latency_seconds = 600
    assert not buffer_decision(value, max_chapters=1).needs_generation


def test_programme_cursor_drives_refill_without_lifecycle_handoff() -> None:
    value = episode(successor=True)
    value.program_transport_active = True
    value.program_playback_position_seconds = 280

    decision = buffer_decision(value)

    assert decision.needs_generation
    assert decision.urgent
    assert decision.current_remaining_seconds == 20


def test_programme_cursor_does_not_require_current_segment_to_advance() -> None:
    value = episode(successor=True)
    value.program_transport_active = True
    value.program_playback_position_seconds = 60
    current_id = value.current_segment_id

    decision = buffer_decision(value)

    assert current_id == "opening"
    assert decision.current_remaining_seconds == 240
