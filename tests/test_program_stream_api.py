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
from wavecast.materialization import MusicSnapshotStore, classify_music_source
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
from tests.test_music_snapshot import FakeFetcher
from tests.test_staged_intelligence import _session


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


def test_gc_reclaims_source_bytes_without_hls_cache_and_protects_live_audio(tmp_path, monkeypatch):
    storage = LocalObjectStorageProvider(tmp_path)
    async def create():
        store = MusicSnapshotStore(storage, FakeFetcher())
        old = await store.snapshot(classify_music_source("/api/audio/sidecar/netease/1"), track_ref="netease:1")
        cached = await storage.get(old.asset_ref)
        metadata = storage.metadata_for(old.asset_ref)
        metadata.pop("source_url")
        metadata.pop("content_sha256")
        await storage.put(old.asset_ref, cached.content, cached.content_type, metadata)
        live = await store.snapshot(classify_music_source("/api/audio/sidecar/netease/2"), track_ref="netease:2")
        await storage.put("narration/paid.mp3", b"paid", "audio/mpeg")
        return old, live
    old, live = asyncio.run(create())
    repo = InMemoryEpisodeRepository()
    repo.save(LiveEpisode(
        id="current", seed_id="seed", title="Radio", topic="Music",
        program_estimated_duration_seconds=900,
        segments=[MusicSegment(
            id="music", chapter_id="one", order=0, title="Music", track_ref="netease:2",
            planned_duration_seconds=240, state=SegmentState.AUDIO_READY,
            audio_source_url=live.playback_url,
        )],
    ))
    old_path = tmp_path / old.asset_ref
    orphan = tmp_path / ".orphan.audio.abcdefgh"
    orphan.write_bytes(b"unpublished")
    os.utime(orphan, (10, 10))
    monkeypatch.setattr(api_module, "repository", repo)
    monkeypatch.setattr(api_module, "AUDIO_ROOT", str(tmp_path))
    monkeypatch.setattr(api_module, "PROGRAM_RENDER_GC_LOW_WATERMARK_BYTES", 100)
    monkeypatch.setattr(api_module, "PROGRAM_RENDER_GC_TARGET_FREE_BYTES", 200)
    monkeypatch.setattr(api_module.shutil, "disk_usage", lambda _:
        shutil._ntuple_diskusage(1000, 950 if old_path.exists() else 750, 50 if old_path.exists() else 250))
    _, free = api_module._gc_program_render_cache("current")
    assert free == 250
    assert not old_path.exists()
    assert len(storage.metadata_for(old.asset_ref)["content_sha256"]) == 64
    assert (tmp_path / live.asset_ref).exists()
    assert (tmp_path / "narration/paid.mp3").exists()
    assert not orphan.exists()
    # A resumed historical episode still has an owned URL in its persisted
    # timeline. The API must restore its cache before the renderer sees it.
    resumed = repo.get("current").model_copy(deep=True)
    resumed.id = "resumed"
    resumed.segments[0].track_ref = "netease:1"
    resumed.segments[0].audio_source_url = old.playback_url
    resumed.segments[0].asset_ref = old.asset_ref
    repo.save(resumed)
    monkeypatch.setattr(api_module, "audio_storage", storage)
    monkeypatch.setattr(api_module, "music_snapshot_store", MusicSnapshotStore(storage, FakeFetcher()))
    monkeypatch.setattr(api_module, "orchestrator", EpisodeOrchestrator(repo))
    prepared = asyncio.run(api_module._prepare_owned_music_assets("resumed", ready_only=True))
    assert prepared.ready
    assert old_path.exists()
    assert repo.get("resumed").segments[0].audio_source_url == old.playback_url


@pytest.mark.parametrize("host_state", [SegmentState.AUDIO_READY, SegmentState.SKIPPED])
def test_progressive_route_closes_only_after_final_host_settles(
    tmp_path, monkeypatch: pytest.MonkeyPatch, host_state: SegmentState,
) -> None:
    async def arrange() -> LocalObjectStorageProvider:
        storage = LocalObjectStorageProvider(tmp_path / "audio")
        await storage.put("music.wav", _wav_bytes(24, 220), "audio/wav")
        await storage.put("outro.wav", _wav_bytes(4, 440), "audio/wav")
        return storage

    storage = asyncio.run(arrange())
    repository = EventLoopRejectingEpisodeRepository()
    runtime = EpisodeOrchestrator(repository)
    monkeypatch.setattr(api_module, "repository", repository)
    monkeypatch.setattr(api_module, "orchestrator", runtime)
    monkeypatch.setattr(api_module, "audio_storage", storage)
    session = _session()
    session.narration_authored_chapter_ids = ["chapter-2", "chapter-3"]
    episode = LiveEpisode(
        seed_id="closure", listener_id="listener-a", state=EpisodeState.STREAMING,
        program_estimated_duration_seconds=900,
        progressive_session=session, current_segment_id="music-1",
        segments=[
            MusicSegment(
                id=f"music-{index}", chapter_id=f"chapter-{index}", order=index - 1,
                state=SegmentState.AUDIO_READY, planned_duration_seconds=24,
                actual_duration_seconds=24, track_ref=f"mock:music-{index}",
                audio_source_url="/api/assets/audio/music.wav", title=f"Music {index}",
            ) for index in range(1, 4)
        ] + [NarrationSegment(
            id="outro", chapter_id="chapter-3", order=3, title="Outro",
            state=SegmentState.SCRIPT_READY, planned_duration_seconds=4,
            narration_text="The programme ends here.", narration_role=NarrationRole.OUTRO,
        )],
    )
    repository.save(episode)
    client = TestClient(api_module.app)
    headers = {"X-Wavecast-Listener": "listener-a"}
    first = client.post(f"/api/episodes/{episode.id}/program-render", headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["complete"] is False
    assert first.json()["chunks"]
    assert "#EXT-X-ENDLIST" not in client.get(first.json()["streamUrl"]).text

    # Writer/TTS succeeds or explicitly degrades. Both outcomes release the
    # genuine ending; no listener action to request FULL is necessary.
    settled = repository.get(episode.id)
    outro = settled.segment("outro")
    outro.state = host_state
    if host_state is SegmentState.AUDIO_READY:
        outro.audio_source_url = "/api/assets/audio/outro.wav"
        outro.actual_duration_seconds = 4
    repository.save(settled)
    final = client.post(f"/api/episodes/{episode.id}/program-render", headers=headers)
    assert final.status_code == 200, final.text
    assert final.json()["complete"] is True
    assert final.json()["chunks"][:len(first.json()["chunks"])] == first.json()["chunks"]
    assert final.json()["renderedFrontierSeconds"] > first.json()["renderedFrontierSeconds"]
    assert "#EXT-X-ENDLIST" in client.get(final.json()["streamUrl"]).text
    frozen = repository.get(episode.id)
    assert frozen.state is EpisodeState.MATERIALIZED
    assert frozen.current_segment_id == "music-1"
    again = client.post(f"/api/episodes/{episode.id}/program-render", headers=headers)
    assert again.json() == final.json()


def test_missing_route_or_unattempted_host_cannot_close_a_programme() -> None:
    episode = LiveEpisode(seed_id="unfinished", program_estimated_duration_seconds=900, segments=[])
    assert not api_module._progressive_programme_ready_to_close(episode)
    episode.progressive_session = _session()
    assert not api_module._progressive_programme_ready_to_close(episode)
    episode.segments = [MusicSegment(
        id=f"music-{index}", chapter_id=f"chapter-{index}", order=index - 1,
        state=SegmentState.AUDIO_READY, planned_duration_seconds=24,
        track_ref=f"mock:music-{index}", title=f"Music {index}",
        audio_source_url="/api/assets/audio/music.wav",
    ) for index in range(1, 4)]
    assert not api_module._progressive_programme_ready_to_close(episode)


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
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = EventLoopRejectingEpisodeRepository()
    orchestrator = EpisodeOrchestrator(repository)
    monkeypatch.setattr(api_module, "repository", repository)
    monkeypatch.setattr(api_module, "orchestrator", orchestrator)
    storage = LocalObjectStorageProvider(tmp_path)
    asyncio.run(storage.put("music/a.wav", _wav_bytes(1, 220), "audio/wav"))
    monkeypatch.setattr(api_module, "audio_storage", storage)

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


def test_program_render_does_not_drop_narration_already_in_frozen_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryEpisodeRepository()
    orchestrator = EpisodeOrchestrator(repository)
    monkeypatch.setattr(api_module, "repository", repository)
    monkeypatch.setattr(api_module, "orchestrator", orchestrator)

    narration = NarrationSegment(
        id="frozen-host",
        chapter_id="chapter-a",
        order=0,
        state=SegmentState.AUDIO_READY,
        planned_duration_seconds=8,
        actual_duration_seconds=8,
        audio_source_url="/api/assets/audio/frozen-host.wav",
        title="Frozen Track Intro",
        narration_text="This host beat is already part of published audio.",
        narration_role=NarrationRole.TRACK_INTRO,
    )
    music = MusicSegment(
        id="music-a",
        chapter_id="chapter-a",
        order=1,
        state=SegmentState.AUDIO_READY,
        planned_duration_seconds=120,
        actual_duration_seconds=120,
        track_ref="track-a",
        audio_source_url="/api/assets/audio/music-a.wav",
        title="A",
        artist="Artist A",
    )
    episode = LiveEpisode(
        id="program-render-frozen-host",
        seed_id="seed",
        title="Frozen host",
        topic="Already published narration stays immutable",
        listener_id="listener-a",
        state=EpisodeState.STREAMING,
        generation_mode=GenerationMode.PROGRESSIVE,
        program_estimated_duration_seconds=240,
        segments=[narration, music],
        current_segment_id="music-a",
    )
    repository.save(episode)
    frozen_plan = api_module.canonical_render_plan_for_episode(episode.id)
    manifest = _manifest_for_plan_prefix(frozen_plan, end_seconds=6)

    skipped = api_module._recover_late_optional_narration_for_frozen_prefix(
        episode.id,
        manifest,
    )

    assert skipped == []
    assert repository.get(episode.id).segment("frozen-host").state is SegmentState.AUDIO_READY
