from __future__ import annotations

import asyncio
import io
import math
import struct
import wave
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient
from wavecast.materialization import MusicSnapshotStore, SnapshotBytes
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
        value = int(9000 * math.sin(2 * math.pi * frequency * index / sample_rate))
        samples.extend(struct.pack("<hh", value, value))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(bytes(samples))
    return buffer.getvalue()


class FakeFetcher:
    def __init__(self) -> None:
        self.calls = 0

    async def fetch(self, source: object) -> SnapshotBytes:
        self.calls += 1
        return SnapshotBytes(
            content=wav_bytes(2, 220 + self.calls * 110),
            content_type="audio/wav",
            duration_seconds=2,
        )


@pytest.mark.skipif(__import__("shutil").which("ffmpeg") is None, reason="ffmpeg is not installed")
def test_prepare_mixdown_snapshots_music_then_existing_mixdown_renders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def arrange() -> LocalObjectStorageProvider:
        storage = LocalObjectStorageProvider(tmp_path / "audio")
        await storage.put("voice-a.wav", wav_bytes(1, 440), "audio/wav")
        return storage

    storage = asyncio.run(arrange())
    fetcher = FakeFetcher()
    snapshot_store = MusicSnapshotStore(storage, fetcher)
    repository = InMemoryEpisodeRepository()
    orchestrator = EpisodeOrchestrator(repository)
    monkeypatch.setattr(api_module, "repository", repository)
    monkeypatch.setattr(api_module, "orchestrator", orchestrator)
    monkeypatch.setattr(api_module, "scheduler", InlineGenerationScheduler(orchestrator))
    monkeypatch.setattr(api_module, "audio_storage", storage)
    monkeypatch.setattr(api_module, "music_snapshot_store", snapshot_store)

    episode = LiveEpisode(
        id="snapshot-api-episode",
        seed_id="seed",
        title="Snapshot",
        topic="Owned music",
        listener_id="listener-a",
        state=EpisodeState.MATERIALIZED,
        generation_mode=GenerationMode.FULL,
        program_estimated_duration_seconds=5,
        segments=[
            MusicSegment(
                id="music-a", chapter_id="chapter-a", order=0,
                state=SegmentState.AUDIO_READY, planned_duration_seconds=2,
                actual_duration_seconds=2, track_ref="track-a",
                audio_source_url="/api/audio/sidecar/mock/a", title="A", artist="Artist A",
            ),
            NarrationSegment(
                id="voice-a", chapter_id="chapter-a", order=1,
                state=SegmentState.AUDIO_READY, planned_duration_seconds=1,
                actual_duration_seconds=1,
                audio_source_url="/api/assets/audio/voice-a.wav", title="Voice",
                narration_text="Bridge",
            ),
            MusicSegment(
                id="music-b", chapter_id="chapter-b", order=2,
                state=SegmentState.AUDIO_READY, planned_duration_seconds=2,
                actual_duration_seconds=2, track_ref="track-b",
                audio_source_url="/api/audio/sidecar/mock/b", title="B", artist="Artist B",
            ),
        ],
        current_segment_id="music-a",
        playback_position_seconds=17,
        is_playing=False,
        last_activity_at=datetime.now(UTC),
        last_heartbeat_at=datetime.now(UTC),
    )
    repository.save(episode)
    before = repository.get(episode.id).model_copy(deep=True)

    client = TestClient(api_module.app)
    prepared = client.post(
        f"/api/episodes/{episode.id}/prepare-mixdown",
        headers={"X-Wavecast-Listener": "listener-a"},
    )

    assert prepared.status_code == 200, prepared.text
    payload = prepared.json()
    assert payload == {
        "episodeId": episode.id,
        "ready": True,
        "ownedMusicCount": 2,
        "snapshottedMusicCount": 2,
        "reusedMusicCount": 0,
        "blockedSources": [],
    }
    stored = repository.get(episode.id)
    music = [segment for segment in stored.segments if isinstance(segment, MusicSegment)]
    assert all(
        isinstance(segment.audio_source_url, str)
        and segment.audio_source_url.startswith("/api/assets/audio/")
        for segment in music
    )
    assert stored.segments[1].audio_source_url == before.segments[1].audio_source_url
    assert stored.current_segment_id == before.current_segment_id
    assert stored.playback_position_seconds == before.playback_position_seconds
    assert stored.is_playing == before.is_playing
    assert [segment.track_ref for segment in stored.segments] == [
        segment.track_ref for segment in before.segments
    ]

    mixed = client.post(
        f"/api/episodes/{episode.id}/mixdown",
        headers={"X-Wavecast-Listener": "listener-a"},
    )
    assert mixed.status_code == 200, mixed.text
    audio_key = unquote(mixed.json()["audioUrl"].split("/api/assets/audio/", 1)[1])
    rendered = asyncio.run(storage.get(audio_key))
    assert rendered is not None
    assert rendered.content_type == "audio/mpeg"
    assert rendered.content


def test_prepare_mixdown_failure_does_not_partially_mutate_episode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FailingFetcher(FakeFetcher):
        async def fetch(self, source: object) -> SnapshotBytes:
            if self.calls:
                raise RuntimeError("provider failure")
            return await super().fetch(source)

    storage = LocalObjectStorageProvider(tmp_path / "audio")
    fetcher = FailingFetcher()
    snapshot_store = MusicSnapshotStore(storage, fetcher)
    repository = InMemoryEpisodeRepository()
    orchestrator = EpisodeOrchestrator(repository)
    monkeypatch.setattr(api_module, "repository", repository)
    monkeypatch.setattr(api_module, "orchestrator", orchestrator)
    monkeypatch.setattr(api_module, "scheduler", InlineGenerationScheduler(orchestrator))
    monkeypatch.setattr(api_module, "audio_storage", storage)
    monkeypatch.setattr(api_module, "music_snapshot_store", snapshot_store)
    episode = LiveEpisode(
        id="snapshot-failure-episode", seed_id="seed", listener_id="listener-a",
        state=EpisodeState.MATERIALIZED, generation_mode=GenerationMode.FULL,
        program_estimated_duration_seconds=4,
        segments=[
            MusicSegment(
                id="music-a", chapter_id="chapter-a", order=0,
                state=SegmentState.AUDIO_READY, planned_duration_seconds=2,
                actual_duration_seconds=2, track_ref="track-a",
                audio_source_url="/api/audio/sidecar/mock/a", title="A",
            ),
            MusicSegment(
                id="music-b", chapter_id="chapter-b", order=1,
                state=SegmentState.AUDIO_READY, planned_duration_seconds=2,
                actual_duration_seconds=2, track_ref="track-b",
                audio_source_url="/api/audio/sidecar/mock/b", title="B",
            ),
        ],
        last_activity_at=datetime.now(UTC), last_heartbeat_at=datetime.now(UTC),
    )
    repository.save(episode)
    before = repository.get(episode.id).model_dump(mode="json")

    response = TestClient(api_module.app).post(
        f"/api/episodes/{episode.id}/prepare-mixdown",
        headers={"X-Wavecast-Listener": "listener-a"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["ready"] is False
    assert response.json()["blockedSources"][0]["reasonCode"] == "snapshot_fetch_failed"
    assert repository.get(episode.id).model_dump(mode="json") == before
