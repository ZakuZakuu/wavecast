from __future__ import annotations

import asyncio
import io
import math
import os
import shutil
import struct
import wave
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from wavecast.arrangement import MixPlan, plan_episode_mix
from wavecast.models.episode import (
    EpisodeState,
    GenerationMode,
    LiveEpisode,
    MusicSegment,
    NarrationRole,
    NarrationSegment,
    PlayableEpisode,
    SegmentState,
)
from wavecast.orchestration import EpisodeOrchestrator, InlineGenerationScheduler
from wavecast.orchestration.episode import InMemoryEpisodeRepository
from wavecast.rendering import ProgramRenderChunk, ProgramRenderManifest, slice_mix_plan
from wavecast.rendering.fingerprint import mix_plan_fingerprint
from wavecast.storage import LocalObjectStorageProvider

import services.api.main as api_module


class EventLoopRejectingEpisodeRepository(InMemoryEpisodeRepository):
    """Regression guard for sync repositories used by async API handlers."""

    @staticmethod
    def _assert_outside_running_loop() -> None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        raise AssertionError("sync episode repository called from a running event loop")

    def get(self, episode_id: str) -> LiveEpisode:
        self._assert_outside_running_loop()
        return super().get(episode_id)

    def save(self, episode: LiveEpisode) -> LiveEpisode:
        self._assert_outside_running_loop()
        return super().save(episode)


def _wav_bytes(duration_seconds: float, frequency: float) -> bytes:
    sample_rate = 8000
    frames = int(sample_rate * duration_seconds)
    samples = bytearray()
    for index in range(frames):
        value = int(9000 * math.sin(2 * math.pi * frequency * index / sample_rate))
        samples.extend(struct.pack("<hh", value, value))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(bytes(samples))
    return buffer.getvalue()


def _manifest_for_plan_prefix(
    plan: MixPlan,
    *,
    end_seconds: float,
) -> ProgramRenderManifest:
    sliced = slice_mix_plan(plan, 0, end_seconds)
    chunk = ProgramRenderChunk(
        index=0,
        start_seconds=0,
        duration_seconds=end_seconds,
        plan_fingerprint=mix_plan_fingerprint(sliced),
        content_sha256="0" * 64,
        asset_key="program-renders/test/chunk.ts",
        audio_url="/api/assets/audio/program-renders/test/chunk.ts",
    )
    return ProgramRenderManifest(
        episode_id=plan.episode_id,
        chunk_duration_seconds=end_seconds,
        holdback_seconds=0,
        rendered_frontier_seconds=end_seconds,
        chunks=(chunk,),
        stream_url=f"/api/program-streams/{plan.episode_id}.m3u8",
    )


def test_program_render_gc_deletes_oldest_cache_until_target(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio_root = tmp_path / "audio"
    cache_root = audio_root / "program-renders"
    old = cache_root / "old-episode"
    current = cache_root / "current-episode"
    newer = cache_root / "newer-episode"
    for path in (old, current, newer):
        path.mkdir(parents=True)
        (path / "chunk.ts").write_bytes(b"x")

    os.utime(old, (10, 10))
    os.utime(current, (20, 20))
    os.utime(newer, (30, 30))

    monkeypatch.setattr(api_module, "AUDIO_ROOT", str(audio_root))
    monkeypatch.setattr(api_module, "PROGRAM_RENDER_GC_LOW_WATERMARK_BYTES", 100)
    monkeypatch.setattr(api_module, "PROGRAM_RENDER_GC_TARGET_FREE_BYTES", 200)

    def fake_disk_usage(_path):
        # 50 bytes free initially; each deleted cache directory recovers 100.
        deleted = sum(not path.exists() for path in (old, newer))
        free = 50 + (100 * deleted)
        return shutil._ntuple_diskusage(total=1000, used=1000 - free, free=free)

    monkeypatch.setattr(api_module.shutil, "disk_usage", fake_disk_usage)

    deleted, free_bytes = api_module._gc_program_render_cache("current-episode")

    assert deleted == 2
    assert free_bytes == 250
    assert not old.exists()
    assert not newer.exists()
    assert current.exists()


def test_program_render_gc_is_noop_above_low_watermark(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio_root = tmp_path / "audio"
    cache = audio_root / "program-renders" / "old-episode"
    cache.mkdir(parents=True)

    monkeypatch.setattr(api_module, "AUDIO_ROOT", str(audio_root))
    monkeypatch.setattr(api_module, "PROGRAM_RENDER_GC_LOW_WATERMARK_BYTES", 100)
    monkeypatch.setattr(
        api_module.shutil,
        "disk_usage",
        lambda _path: shutil._ntuple_diskusage(total=1000, used=800, free=200),
    )

    deleted, free_bytes = api_module._gc_program_render_cache("current-episode")

    assert deleted == 0
    assert free_bytes == 200
    assert cache.exists()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
def test_program_stream_renders_idempotent_single_feed_without_mutating_episode(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def arrange() -> LocalObjectStorageProvider:
        storage = LocalObjectStorageProvider(tmp_path / "audio")
        await storage.put("music-a.wav", _wav_bytes(2.5, 220), "audio/wav")
        await storage.put("voice-a.wav", _wav_bytes(1.5, 440), "audio/wav")
        await storage.put("music-b.wav", _wav_bytes(2.5, 330), "audio/wav")
        return storage

    storage = asyncio.run(arrange())
    repository = EventLoopRejectingEpisodeRepository()
    orchestrator = EpisodeOrchestrator(repository)
    monkeypatch.setattr(api_module, "repository", repository)
    monkeypatch.setattr(api_module, "orchestrator", orchestrator)
    monkeypatch.setattr(api_module, "scheduler", InlineGenerationScheduler(orchestrator))
    monkeypatch.setattr(api_module, "audio_storage", storage)

    episode = LiveEpisode(
        id="program-stream-api-episode",
        seed_id="seed",
        title="Program stream",
        topic="Immutable playback",
        listener_id="listener-a",
        state=EpisodeState.MATERIALIZED,
        generation_mode=GenerationMode.FULL,
        program_estimated_duration_seconds=5,
        segments=[
            MusicSegment(
                id="music-a",
                chapter_id="chapter-a",
                order=0,
                state=SegmentState.AUDIO_READY,
                planned_duration_seconds=2,
                actual_duration_seconds=2,
                track_ref="track-a",
                audio_source_url="/api/assets/audio/music-a.wav",
                title="A",
                artist="Artist A",
            ),
            NarrationSegment(
                id="voice-a",
                chapter_id="chapter-a",
                order=1,
                state=SegmentState.AUDIO_READY,
                planned_duration_seconds=1,
                actual_duration_seconds=1,
                audio_source_url="/api/assets/audio/voice-a.wav",
                title="Voice",
                narration_text="Bridge",
            ),
            MusicSegment(
                id="music-b",
                chapter_id="chapter-b",
                order=2,
                state=SegmentState.AUDIO_READY,
                planned_duration_seconds=2,
                actual_duration_seconds=2,
                track_ref="track-b",
                audio_source_url="/api/assets/audio/music-b.wav",
                title="B",
                artist="Artist B",
            ),
        ],
        current_segment_id="music-a",
        last_activity_at=datetime.now(UTC),
        last_heartbeat_at=datetime.now(UTC),
    )
    repository.save(episode)
    before = repository.get(episode.id).model_dump(mode="json")
    client = TestClient(api_module.app)
    headers = {"X-Wavecast-Listener": "listener-a"}

    first = client.post(
        f"/api/episodes/{episode.id}/program-render",
        headers=headers,
    )
    assert first.status_code == 200, first.text
    manifest = first.json()
    assert manifest["episodeId"] == episode.id
    assert manifest["complete"] is True
    assert manifest["renderedFrontierSeconds"] > 0
    assert len(manifest["chunks"]) >= 1

    second = client.post(
        f"/api/episodes/{episode.id}/program-render",
        headers=headers,
    )
    assert second.status_code == 200, second.text
    assert second.json() == manifest

    playlist = client.get(manifest["streamUrl"])
    assert playlist.status_code == 200, playlist.text
    assert playlist.headers["content-type"].startswith("application/vnd.apple.mpegurl")
    assert "#EXT-X-PLAYLIST-TYPE:EVENT" in playlist.text
    assert "#EXT-X-ENDLIST" in playlist.text
    for chunk in manifest["chunks"]:
        assert chunk["audioUrl"] in playlist.text
        asset = client.get(chunk["audioUrl"])
        assert asset.status_code == 200
        assert asset.headers["content-type"].startswith("video/mp2t")
        assert asset.content

    assert repository.get(episode.id).model_dump(mode="json") == before


def test_progressive_render_snapshot_ignores_unready_future_music(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = EventLoopRejectingEpisodeRepository()
    orchestrator = EpisodeOrchestrator(repository)
    monkeypatch.setattr(api_module, "repository", repository)
    monkeypatch.setattr(api_module, "orchestrator", orchestrator)

    episode = LiveEpisode(
        id="program-render-ready-only",
        seed_id="seed",
        title="Ready prefix",
        topic="Future music must not block",
        listener_id="listener-a",
        state=EpisodeState.STREAMING,
        generation_mode=GenerationMode.PROGRESSIVE,
        program_estimated_duration_seconds=240,
        segments=[
            MusicSegment(
                id="music-a",
                chapter_id="chapter-a",
                order=0,
                state=SegmentState.AUDIO_READY,
                planned_duration_seconds=120,
                actual_duration_seconds=120,
                track_ref="track-a",
                audio_source_url="/api/assets/audio/music/a.wav",
                title="A",
                artist="Artist A",
            ),
            MusicSegment(
                id="music-b",
                chapter_id="chapter-b",
                order=1,
                state=SegmentState.PLANNED,
                planned_duration_seconds=120,
                track_ref="track-b",
                title="B",
                artist="Artist B",
            ),
        ],
        current_segment_id="music-a",
    )
    repository.save(episode)

    result = asyncio.run(
        api_module._prepare_owned_music_assets(
            episode.id,
            ready_only=True,
        )
    )

    assert result.ready is True
    assert result.owned_music_count == 1
    assert result.blocked_sources == []


def test_render_plan_can_freeze_past_explicitly_skipped_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryEpisodeRepository()
    orchestrator = EpisodeOrchestrator(repository)
    monkeypatch.setattr(api_module, "repository", repository)
    monkeypatch.setattr(api_module, "orchestrator", orchestrator)

    episode = LiveEpisode(
        id="program-render-skipped-host",
        seed_id="seed",
        title="Skipped host",
        topic="Persisted editorial skip",
        listener_id="listener-a",
        state=EpisodeState.STREAMING,
        generation_mode=GenerationMode.PROGRESSIVE,
        program_estimated_duration_seconds=240,
        segments=[
            MusicSegment(
                id="music-a",
                chapter_id="chapter-a",
                order=0,
                state=SegmentState.AUDIO_READY,
                planned_duration_seconds=120,
                actual_duration_seconds=120,
                track_ref="track-a",
                audio_source_url="/api/assets/audio/music-a.wav",
                title="A",
                artist="Artist A",
            ),
            NarrationSegment(
                id="voice-a",
                chapter_id="chapter-b",
                order=1,
                state=SegmentState.SKIPPED,
                planned_duration_seconds=8,
                title="Skipped host",
                narration_text="Skipped",
            ),
            MusicSegment(
                id="music-b",
                chapter_id="chapter-b",
                order=2,
                state=SegmentState.AUDIO_READY,
                planned_duration_seconds=120,
                actual_duration_seconds=120,
                track_ref="track-b",
                audio_source_url="/api/assets/audio/music-b.wav",
                title="B",
                artist="Artist B",
            ),
        ],
        current_segment_id="music-a",
    )
    repository.save(episode)

    plan = api_module.canonical_render_plan_for_episode(episode.id)

    assert {clip.segment_id for clip in plan.clips} == {"music-a", "music-b"}


def test_render_plan_waits_for_unready_host_instead_of_skipping_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryEpisodeRepository()
    orchestrator = EpisodeOrchestrator(repository)
    monkeypatch.setattr(api_module, "repository", repository)
    monkeypatch.setattr(api_module, "orchestrator", orchestrator)

    episode = LiveEpisode(
        id="program-render-host-wait",
        seed_id="seed",
        title="Host wait",
        topic="Do not freeze through pending narration",
        listener_id="listener-a",
        state=EpisodeState.STREAMING,
        generation_mode=GenerationMode.PROGRESSIVE,
        program_estimated_duration_seconds=240,
        segments=[
            MusicSegment(
                id="music-a",
                chapter_id="chapter-a",
                order=0,
                state=SegmentState.AUDIO_READY,
                planned_duration_seconds=120,
                actual_duration_seconds=120,
                track_ref="track-a",
                audio_source_url="/api/assets/audio/music-a.wav",
                title="A",
                artist="Artist A",
            ),
            NarrationSegment(
                id="voice-a",
                chapter_id="chapter-b",
                order=1,
                state=SegmentState.SCRIPT_READY,
                planned_duration_seconds=8,
                title="Pending host",
                narration_text="Pending",
            ),
            MusicSegment(
                id="music-b",
                chapter_id="chapter-b",
                order=2,
                state=SegmentState.AUDIO_READY,
                planned_duration_seconds=120,
                actual_duration_seconds=120,
                track_ref="track-b",
                audio_source_url="/api/assets/audio/music-b.wav",
                title="B",
                artist="Artist B",
            ),
        ],
        current_segment_id="music-a",
    )
    repository.save(episode)

    plan = api_module.canonical_render_plan_for_episode(episode.id)

    assert {clip.segment_id for clip in plan.clips} == {"music-a"}
    assert plan.duration_seconds == 120


def test_program_render_continuity_deadline_skips_pending_host_before_ready_music(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryEpisodeRepository()
    orchestrator = EpisodeOrchestrator(repository)
    monkeypatch.setattr(api_module, "repository", repository)
    monkeypatch.setattr(api_module, "orchestrator", orchestrator)

    episode = LiveEpisode(
        id="program-render-continuity-deadline",
        seed_id="seed",
        title="Continuity deadline",
        topic="Optional host must not strand ready music",
        listener_id="listener-a",
        state=EpisodeState.STREAMING,
        generation_mode=GenerationMode.PROGRESSIVE,
        program_estimated_duration_seconds=360,
        program_transport_active=True,
        program_playback_position_seconds=100,
        segments=[
            MusicSegment(
                id="music-a",
                chapter_id="chapter-a",
                order=0,
                state=SegmentState.AUDIO_READY,
                planned_duration_seconds=120,
                actual_duration_seconds=120,
                track_ref="track-a",
                audio_source_url="/api/assets/audio/music-a.wav",
                title="A",
                artist="Artist A",
            ),
            NarrationSegment(
                id="host-b",
                chapter_id="chapter-b",
                order=1,
                state=SegmentState.SCRIPT_READY,
                planned_duration_seconds=12,
                title="Pending host",
                narration_text="A late optional bridge.",
                narration_role=NarrationRole.TRACK_INTRO,
            ),
            MusicSegment(
                id="music-b",
                chapter_id="chapter-b",
                order=2,
                state=SegmentState.AUDIO_READY,
                planned_duration_seconds=120,
                actual_duration_seconds=120,
                track_ref="track-b",
                audio_source_url="/api/assets/audio/music-b.wav",
                title="B",
                artist="Artist B",
            ),
        ],
        current_segment_id="music-a",
    )
    repository.save(episode)
    manifest = ProgramRenderManifest(
        episode_id=episode.id,
        chunk_duration_seconds=120,
        holdback_seconds=30,
        rendered_frontier_seconds=120,
        chunks=(
            ProgramRenderChunk(
                index=0,
                start_seconds=0,
                duration_seconds=120,
                plan_fingerprint="previous-plan",
                content_sha256="0" * 64,
                asset_key="program-renders/test/chunk.ts",
                audio_url="/api/assets/audio/program-renders/test/chunk.ts",
            ),
        ),
        stream_url=f"/api/program-streams/{episode.id}.m3u8",
    )

    skipped = api_module._skip_blocking_optional_narration_for_continuity(
        episode.id,
        manifest,
    )

    assert skipped == ["host-b"]
    assert repository.get(episode.id).segment("host-b").state is SegmentState.SKIPPED


def test_program_render_recovers_only_when_late_narration_removal_restores_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryEpisodeRepository()
    orchestrator = EpisodeOrchestrator(repository)
    monkeypatch.setattr(api_module, "repository", repository)
    monkeypatch.setattr(api_module, "orchestrator", orchestrator)

    music = MusicSegment(
        id="music-a",
        chapter_id="chapter-a",
        order=0,
        state=SegmentState.AUDIO_READY,
        planned_duration_seconds=120,
        actual_duration_seconds=120,
        track_ref="track-a",
        audio_source_url="/api/assets/audio/music-a.wav",
        title="A",
        artist="Artist A",
    )
    previous = plan_episode_mix(
        PlayableEpisode(
            id="program-render-late-host",
            segments=[music],
        )
    )
    manifest = _manifest_for_plan_prefix(previous, end_seconds=6)

    episode = LiveEpisode(
        id=previous.episode_id,
        seed_id="seed",
        title="Late host",
        topic="Frozen prefix admission",
        listener_id="listener-a",
        state=EpisodeState.STREAMING,
        generation_mode=GenerationMode.PROGRESSIVE,
        program_estimated_duration_seconds=240,
        segments=[
            NarrationSegment(
                id="late-host",
                chapter_id="chapter-a",
                order=0,
                state=SegmentState.AUDIO_READY,
                planned_duration_seconds=8,
                actual_duration_seconds=8,
                audio_source_url="/api/assets/audio/late-host.wav",
                title="Late Track Intro",
                narration_text="This arrived after the programme had already published.",
                narration_role=NarrationRole.TRACK_INTRO,
            ),
            music.model_copy(update={"order": 1}),
        ],
        current_segment_id="music-a",
    )
    repository.save(episode)

    current_plan = api_module.canonical_render_plan_for_episode(episode.id)
    assert not api_module.frozen_prefix_is_compatible(current_plan, manifest)

    skipped = api_module._recover_late_optional_narration_for_frozen_prefix(
        episode.id,
        manifest,
    )

    assert skipped == ["late-host"]
    recovered = repository.get(episode.id)
    assert recovered.segment("late-host").state is SegmentState.SKIPPED
    assert api_module.frozen_prefix_is_compatible(
        api_module.canonical_render_plan_for_episode(episode.id),
        manifest,
    )
