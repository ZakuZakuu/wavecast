from __future__ import annotations

import asyncio
import io
import math
import struct
import wave
from datetime import UTC, datetime
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient
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

import services.api.main as api_module


def wav_bytes(duration_seconds: float, frequency: float) -> bytes:
    sample_rate = 8000
    frames = int(sample_rate * duration_seconds)
    samples = bytearray()
    for index in range(frames):
        value = int(10000 * math.sin(2 * math.pi * frequency * index / sample_rate))
        samples.extend(struct.pack("<hh", value, value))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(bytes(samples))
    return buffer.getvalue()


@pytest.mark.skipif(__import__("shutil").which("ffmpeg") is None, reason="ffmpeg is not installed")
def test_mixdown_endpoint_renders_owned_sources_without_mutating_episode(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def arrange() -> LocalObjectStorageProvider:
        storage = LocalObjectStorageProvider(tmp_path / "audio")
        await storage.put("music-a.wav", wav_bytes(2.5, 220), "audio/wav")
        await storage.put("voice-a.wav", wav_bytes(1.5, 440), "audio/wav")
        await storage.put("music-b.wav", wav_bytes(2.5, 330), "audio/wav")
        return storage

    storage = asyncio.run(arrange())
    repository = InMemoryEpisodeRepository()
    orchestrator = EpisodeOrchestrator(repository)
    monkeypatch.setattr(api_module, "repository", repository)
    monkeypatch.setattr(api_module, "orchestrator", orchestrator)
    monkeypatch.setattr(api_module, "scheduler", InlineGenerationScheduler(orchestrator))
    monkeypatch.setattr(api_module, "audio_storage", storage)

    episode = LiveEpisode(
        id="mixdown-api-episode",
        seed_id="seed",
        title="Mixdown",
        topic="Offline rendering",
        listener_id="listener-a",
        state=EpisodeState.MATERIALIZED,
        generation_mode=GenerationMode.FULL,
        program_estimated_duration_seconds=4,
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
    before = episode.model_dump(mode="json")

    response = TestClient(api_module.app).post(
        f"/api/episodes/{episode.id}/mixdown",
        headers={"X-Wavecast-Listener": "listener-a"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["episodeId"] == episode.id
    assert unquote(payload["audioUrl"]).startswith("/api/assets/audio/mixdowns/")
    assert payload["contentType"] == "audio/mpeg"
    stored = asyncio.run(storage.get(unquote(payload["audioUrl"].split("/api/assets/audio/", 1)[1])))
    assert stored is not None
    assert stored.content_type == "audio/mpeg"
    assert stored.content
    assert repository.get(episode.id).model_dump(mode="json") == before
