from __future__ import annotations

import asyncio
import io
import math
import shutil
import struct
import wave
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

import services.api.main as api_module
from wavecast.models.episode import (
    EpisodeState,
    GenerationMode,
    LiveEpisode,
    MusicSegment,
    NarrationSegment,
    SegmentState,
)
from wavecast.orchestration import EpisodeOrchestrator, InlineGenerationScheduler
from wavecast.orchestration.episode import InMemoryEpisodeRepository
from wavecast.storage import LocalObjectStorageProvider


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
    repository = InMemoryEpisodeRepository()
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
