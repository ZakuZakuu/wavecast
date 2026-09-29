
from __future__ import annotations

import asyncio

import pytest
from wavecast.models.episode import (
    CoverParams,
    EpisodeSeed,
    EpisodeState,
    LiveEpisode,
    MusicSegment,
    NarrationSegment,
    SegmentState,
)
from wavecast.orchestration.episode import (
    EpisodeOrchestrator,
    EpisodeRuntimeError,
    InMemoryEpisodeRepository,
)
from wavecast.orchestration.generation import GeneratedChapter
from wavecast.providers.errors import ProviderTimeoutError


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


def test_opening_track_is_ready_immediately_and_future_is_generated_on_demand(
    runtime: EpisodeOrchestrator, seed: EpisodeSeed
) -> None:
    episode = runtime.start(seed)
    assert episode.state is EpisodeState.STREAMING
    assert episode.generated_frontier_seconds == 22
    assert len(episode.ordered_segments) == 1
    assert episode.ordered_segments[0].is_audio_ready

    updated = runtime.ensure_buffer(episode.id, target_chapters=1, target_ahead_seconds=300)
    assert updated.generated_frontier_seconds > 32
    assert updated.segment("segment-narration-1").is_audio_ready
    assert updated.segment("segment-bridge").is_audio_ready


def test_verified_seed_duration_overrides_audio_provider_fallback(
    runtime: EpisodeOrchestrator, seed: EpisodeSeed
) -> None:
    verified = seed.model_copy(update={"opening_track_duration_seconds": 187})

    episode = runtime.start(verified)
    opening = episode.segment("segment-opening")

    assert opening.duration_seconds == 187
    assert episode.generated_frontier_seconds == 187
    assert opening.audio_source_url is not None


def test_timeline_serializes_explicit_playable_audio_segment_fields(
    runtime: EpisodeOrchestrator, seed: EpisodeSeed
) -> None:
    episode = runtime.start(seed)
    runtime.ensure_buffer(episode.id, target_chapters=1, target_ahead_seconds=300)
    opening = runtime.get(episode.id).segment("segment-opening")
    narration = runtime.get(episode.id).segment("segment-narration-1")

    opening_payload = opening.model_dump(mode="json")
    assert opening_payload["audio_source_url"].startswith("/api/audio/mock/music/")
    assert opening_payload["duration_seconds"] == 22
    assert narration.model_dump(mode="json")["audio_source_url"].startswith(
        "/api/audio/mock/narration/"
    )


def test_browser_completion_transitions_segments_without_server_clock(
    runtime: EpisodeOrchestrator, seed: EpisodeSeed
) -> None:
    episode = runtime.start(seed)
    runtime.ensure_buffer(episode.id, target_chapters=1, target_ahead_seconds=300)
    runtime.checkpoint_playback(episode.id, 7)

    completed = runtime.complete_current_segment(episode.id)

    assert completed.segment("segment-opening").state is SegmentState.PLAYED
    assert completed.current_segment_id == "segment-narration-1"
    assert completed.playback_position_seconds == 22
    assert completed.is_playing is True


def test_armed_handoff_locks_successor_without_changing_current_segment(
    runtime: EpisodeOrchestrator, seed: EpisodeSeed
) -> None:
    episode = runtime.start(seed)
    runtime.ensure_buffer(episode.id, target_chapters=1, target_ahead_seconds=300)
    staged = runtime.get(episode.id)
    staged.segment("segment-narration-1").state = SegmentState.SCRIPT_READY
    runtime.repository.save(staged)

    armed = runtime.arm_handoff(episode.id, "segment-bridge")

    assert armed.current_segment_id == "segment-opening"
    assert armed.segment("segment-opening").state is SegmentState.COMMITTED
    assert armed.segment("segment-narration-1").state is SegmentState.SKIPPED
    assert armed.segment("segment-bridge").state is SegmentState.COMMITTED
    assert armed.playback_position_seconds == 0

    completed = runtime.complete_current_segment(episode.id)
    assert completed.segment("segment-opening").state is SegmentState.PLAYED
    assert completed.current_segment_id == "segment-bridge"
    assert completed.segment("segment-bridge").state is SegmentState.COMMITTED


def test_complete_handoff_is_idempotent_after_browser_switch(
    runtime: EpisodeOrchestrator, seed: EpisodeSeed
) -> None:
    episode = runtime.start(seed)
    runtime.ensure_buffer(episode.id, target_chapters=1, target_ahead_seconds=300)
    staged = runtime.get(episode.id)
    staged.segment("segment-narration-1").state = SegmentState.SCRIPT_READY
    runtime.repository.save(staged)
    runtime.arm_handoff(episode.id, "segment-bridge")

    completed = runtime.complete_handoff(
        episode.id,
        "segment-opening",
        "segment-bridge",
    )
    assert completed.segment("segment-opening").state is SegmentState.PLAYED
    assert completed.current_segment_id == "segment-bridge"
    assert completed.segment("segment-bridge").state is SegmentState.COMMITTED

    repeated = runtime.complete_handoff(
        episode.id,
        "segment-opening",
        "segment-bridge",
    )
    assert repeated.segment("segment-opening").state is SegmentState.PLAYED
    assert repeated.current_segment_id == "segment-bridge"
    assert repeated.segment("segment-bridge").state is SegmentState.COMMITTED


def test_armed_handoff_rejects_a_stale_successor_identity_without_side_effects(
    runtime: EpisodeOrchestrator, seed: EpisodeSeed
) -> None:
    episode = runtime.start(seed)
    runtime.ensure_buffer(episode.id, target_chapters=1, target_ahead_seconds=300)
    staged = runtime.get(episode.id)
    staged.segment("segment-narration-1").state = SegmentState.SCRIPT_READY
    runtime.repository.save(staged)

    with pytest.raises(EpisodeRuntimeError, match="successor changed"):
        runtime.arm_handoff(episode.id, "stale-successor")

    unchanged = runtime.get(episode.id)
    assert unchanged.segment("segment-narration-1").state is SegmentState.SCRIPT_READY
    assert unchanged.segment("segment-bridge").state is SegmentState.AUDIO_READY


def test_stale_ended_event_cannot_advance_a_new_seek_target(
    runtime: EpisodeOrchestrator, seed: EpisodeSeed
) -> None:
    episode = runtime.start(seed)
    runtime.ensure_buffer(episode.id, target_chapters=1, target_ahead_seconds=300)
    buffered = runtime.get(episode.id)
    opening = buffered.segment("segment-opening")
    narration = buffered.segment("segment-narration-1")
    bridge_start = opening.duration_seconds + narration.duration_seconds

    sought = runtime.seek(episode.id, bridge_start)
    assert sought.current_segment_id == "segment-bridge"

    with pytest.raises(EpisodeRuntimeError, match="completed segment is stale"):
        runtime.complete_current_segment(
            episode.id,
            expected_segment_id="segment-opening",
        )

    unchanged = runtime.get(episode.id)
    assert unchanged.current_segment_id == "segment-bridge"
    assert unchanged.segment("segment-bridge").state is SegmentState.COMMITTED
    assert unchanged.segment("segment-opening").state is not SegmentState.PLAYED


def test_seek_cannot_cross_generated_frontier(
    runtime: EpisodeOrchestrator, seed: EpisodeSeed
) -> None:
    episode = runtime.start(seed)
    runtime.seek(episode.id, 10)
    assert runtime.get(episode.id).playback_position_seconds == 10

    with pytest.raises(EpisodeRuntimeError, match="generated frontier"):
        runtime.seek(episode.id, 23)


def test_buffer_ahead_tracks_generated_frontier_minus_browser_position(
    runtime: EpisodeOrchestrator, seed: EpisodeSeed
) -> None:
    episode = runtime.start(seed)
    runtime.ensure_buffer(episode.id, target_chapters=1, target_ahead_seconds=300)

    checkpointed = runtime.checkpoint_playback(episode.id, 9)

    assert checkpointed.buffer_ahead_seconds == (
        checkpointed.generated_frontier_seconds - checkpointed.playback_position_seconds
    )


def test_seconds_target_stops_after_one_generated_chapter(
    runtime: EpisodeOrchestrator, seed: EpisodeSeed
) -> None:
    episode = runtime.start(seed)

    buffered = runtime.ensure_buffer(
        episode.id, target_chapters=2, target_ahead_seconds=30
    )

    assert buffered.buffer_ahead_seconds >= 30
    assert buffered.segment("segment-narration-1").is_audio_ready
    assert buffered.segment("segment-bridge").is_audio_ready
    with pytest.raises(KeyError):
        buffered.segment("segment-narration-2")


def test_two_chapter_target_generates_only_two_chapters(
    runtime: EpisodeOrchestrator, seed: EpisodeSeed
) -> None:
    episode = runtime.start(seed)

    buffered = runtime.ensure_buffer(episode.id, target_chapters=2, target_ahead_seconds=300)

    assert buffered.segment("segment-resolution").is_audio_ready
    with pytest.raises(KeyError):
        buffered.segment("segment-narration-3")


def test_replan_preserves_committed_content(
    runtime: EpisodeOrchestrator, seed: EpisodeSeed
) -> None:
    episode = runtime.start(seed)
    runtime.ensure_buffer(episode.id, target_chapters=1, target_ahead_seconds=300)
    runtime.commit_segment(episode.id, "segment-opening")
    runtime.replace_speculative_music(episode.id, "A new future route")

    updated = runtime.get(episode.id)
    assert updated.segment("segment-opening").title == "Immediate opening"
    assert updated.segment("segment-opening").is_committed
    assert updated.segment("segment-bridge").title == "Midnight Transfer"


def test_next_uses_known_music_when_narration_is_not_ready(
    runtime: EpisodeOrchestrator, seed: EpisodeSeed
) -> None:
    episode = runtime.start(seed)
    runtime.ensure_buffer(episode.id, target_chapters=1, target_ahead_seconds=300)
    current = runtime.get(episode.id)
    current.segment("segment-narration-1").state = SegmentState.SCRIPT_READY
    runtime.repository.save(current)

    updated = runtime.next_playable(episode.id)
    assert updated.current_segment_id == "segment-bridge"
    assert updated.segment("segment-bridge").is_committed
    assert updated.segment("segment-narration-1").state is SegmentState.SKIPPED


def test_unready_narration_does_not_hide_ready_music_or_create_dead_air(
    runtime: EpisodeOrchestrator, seed: EpisodeSeed
) -> None:
    episode = runtime.start(seed)
    runtime.ensure_buffer(episode.id, target_chapters=1, target_ahead_seconds=300)
    staged = runtime.get(episode.id)
    staged.segment("segment-narration-1").state = SegmentState.SCRIPT_READY
    staged = runtime.repository.save(staged)

    assert staged.generated_frontier_seconds == 22
    assert staged.buffer_ahead_seconds == 22
    assert staged.has_ready_successor is True
    assert staged.ready_audio_seconds_ahead > staged.buffer_ahead_seconds

    continued = runtime.complete_current_segment(episode.id)

    assert continued.segment("segment-narration-1").state is SegmentState.SKIPPED
    assert continued.current_segment_id == "segment-bridge"
    assert continued.is_playing is True


def test_ready_narration_without_future_music_is_not_a_healthy_successor(
    runtime: EpisodeOrchestrator, seed: EpisodeSeed
) -> None:
    episode = runtime.start(seed)
    snapshot = runtime.capture_generation_snapshot(episode.id)
    runtime.append_generated_chapter(
        episode.id,
        GeneratedChapter(
            chapter_id="chapter-2",
            segments=[
                NarrationSegment(
                    id="chapter-2:narration-only",
                    chapter_id="chapter-2",
                    order=0,
                    state=SegmentState.AUDIO_READY,
                    planned_duration_seconds=30,
                    actual_duration_seconds=30,
                    audio_source_url="/api/assets/audio/narration-only.mp3",
                    title="Narration only",
                    narration_text="This is not a music buffer.",
                )
            ],
        ),
        snapshot,
    )

    updated = runtime.get(episode.id)
    assert updated.has_ready_successor is False
    assert runtime._ready_future_chapter_count(updated) == 0


class _NarrationEnrichmentRuntime:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    async def prepare_session(self, episode: LiveEpisode):
        raise AssertionError("narration enrichment test must not prepare a session")

    def create_generator(self, session):
        raise AssertionError("narration enrichment test must not generate a chapter")

    async def materialize_narration(
        self, segment: NarrationSegment
    ) -> NarrationSegment:
        self.calls += 1
        if self.fail:
            raise ProviderTimeoutError("tts timeout")
        return segment.model_copy(
            update={
                "state": SegmentState.AUDIO_READY,
                "asset_ref": "asset:narration",
                "audio_source_url": "/api/assets/audio/narration.mp3",
                "actual_duration_seconds": segment.planned_duration_seconds,
            }
        )


def _append_script_ready_narration_with_ready_music(
    runtime: EpisodeOrchestrator, episode_id: str
) -> None:
    snapshot = runtime.capture_generation_snapshot(episode_id)
    runtime.append_generated_chapter(
        episode_id,
        GeneratedChapter(
            chapter_id="chapter-2",
            segments=[
                NarrationSegment(
                    id="chapter-2:narration:0",
                    chapter_id="chapter-2",
                    order=0,
                    state=SegmentState.SCRIPT_READY,
                    planned_duration_seconds=5,
                    title="Bridge",
                    narration_text="A short bridge.",
                ),
                MusicSegment(
                    id="chapter-2:music:0",
                    chapter_id="chapter-2",
                    order=1,
                    state=SegmentState.AUDIO_READY,
                    planned_duration_seconds=180,
                    actual_duration_seconds=180,
                    track_ref="mock:bridge",
                    audio_source_url="/api/audio/mock/music/mock%3Abridge",
                    title="Bridge Track",
                    artist="Bridge Artist",
                ),
            ],
        ),
        snapshot,
    )


def test_narration_enrichment_attaches_audio_after_ready_music_is_persisted(
    seed: EpisodeSeed,
) -> None:
    enrichment = _NarrationEnrichmentRuntime()
    repository = InMemoryEpisodeRepository()
    runtime = EpisodeOrchestrator(
        repository,
        progressive_runtime=enrichment,  # type: ignore[arg-type]
    )
    episode = runtime.start(seed)
    _append_script_ready_narration_with_ready_music(runtime, episode.id)

    before = runtime.get(episode.id)
    assert before.segment("chapter-2:narration:0").state is SegmentState.SCRIPT_READY
    assert before.segment("chapter-2:music:0").is_audio_ready
    assert before.has_ready_successor is True

    enriched = asyncio.run(
        runtime.materialize_pending_narration_async(episode.id, max_segments=1)
    )

    narration = enriched.segment("chapter-2:narration:0")
    assert enrichment.calls == 1
    assert narration.state is SegmentState.AUDIO_READY
    assert narration.audio_source_url == "/api/assets/audio/narration.mp3"
    assert enriched.segment("chapter-2:music:0").is_audio_ready


class _UnexpectedNarrationEnrichmentRuntime(_NarrationEnrichmentRuntime):
    async def materialize_narration(
        self, segment: NarrationSegment
    ) -> NarrationSegment:
        self.calls += 1
        del segment
        raise RuntimeError("synthetic unexpected TTS failure")


def test_unexpected_tts_failure_also_skips_only_speculative_narration(
    seed: EpisodeSeed,
) -> None:
    enrichment = _UnexpectedNarrationEnrichmentRuntime()
    repository = InMemoryEpisodeRepository()
    runtime = EpisodeOrchestrator(
        repository,
        progressive_runtime=enrichment,  # type: ignore[arg-type]
    )
    episode = runtime.start(seed)
    _append_script_ready_narration_with_ready_music(runtime, episode.id)

    enriched = asyncio.run(
        runtime.materialize_pending_narration_async(episode.id, max_segments=1)
    )

    assert enrichment.calls == 1
    assert enriched.segment("chapter-2:narration:0").state is SegmentState.SKIPPED
    assert enriched.segment("chapter-2:music:0").is_audio_ready
    assert enriched.has_ready_successor is True


def test_tts_failure_skips_only_speculative_narration(
    seed: EpisodeSeed,
) -> None:
    enrichment = _NarrationEnrichmentRuntime(fail=True)
    repository = InMemoryEpisodeRepository()
    runtime = EpisodeOrchestrator(
        repository,
        progressive_runtime=enrichment,  # type: ignore[arg-type]
    )
    episode = runtime.start(seed)
    _append_script_ready_narration_with_ready_music(runtime, episode.id)

    enriched = asyncio.run(
        runtime.materialize_pending_narration_async(episode.id, max_segments=1)
    )

    assert enrichment.calls == 1
    assert enriched.segment("chapter-2:narration:0").state is SegmentState.SKIPPED
    assert enriched.segment("chapter-2:music:0").is_audio_ready
    assert enriched.has_ready_successor is True


def test_exit_cancels_future_progress_and_resume_restarts_it(
    runtime: EpisodeOrchestrator, seed: EpisodeSeed
) -> None:
    episode = runtime.start(seed)
    runtime.leave(episode.id)
    with pytest.raises(EpisodeRuntimeError, match="session is inactive"):
        runtime.ensure_buffer(episode.id)
    assert runtime.get(episode.id).generated_frontier_seconds == 22

    runtime.resume(episode.id)
    advanced = runtime.ensure_buffer(episode.id, target_chapters=1, target_ahead_seconds=300)
    assert advanced.generated_frontier_seconds > 22


def test_full_materialization_makes_a_fixed_complete_timeline(
    runtime: EpisodeOrchestrator, seed: EpisodeSeed
) -> None:
    episode = runtime.start(seed)
    materialized = runtime.materialize_all(episode.id)
    assert materialized.state is EpisodeState.MATERIALIZED
    assert materialized.generated_frontier_seconds == materialized.timeline_duration_seconds
    assert len(materialized.ordered_segments) == 7

    after_advance = runtime.ensure_buffer(episode.id)
    assert after_advance.model_dump() == materialized.model_dump()
