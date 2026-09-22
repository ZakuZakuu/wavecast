from collections.abc import Generator
from datetime import UTC, datetime

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

import services.api.main as api_module


@pytest.fixture
def canonical_episode(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[LiveEpisode, None, None]:
    repository = InMemoryEpisodeRepository()
    orchestrator = EpisodeOrchestrator(repository)
    old = (api_module.repository, api_module.orchestrator, api_module.scheduler)
    monkeypatch.setattr(api_module, "repository", repository)
    monkeypatch.setattr(api_module, "orchestrator", orchestrator)
    monkeypatch.setattr(api_module, "scheduler", InlineGenerationScheduler(orchestrator))
    episode = LiveEpisode(
        id="canonical-mix-plan-episode",
        seed_id="seed",
        title="Canonical",
        topic="Mix plan",
        listener_id="listener-a",
        state=EpisodeState.MATERIALIZED,
        generation_mode=GenerationMode.FULL,
        program_estimated_duration_seconds=90,
        segments=[
            MusicSegment(
                id="music-a",
                chapter_id="chapter-a",
                order=0,
                state=SegmentState.AUDIO_READY,
                planned_duration_seconds=40,
                actual_duration_seconds=40,
                track_ref="track-a",
                audio_source_url="/api/audio/mock/music/a?duration=40",
                title="A",
                artist="Artist A",
            ),
            NarrationSegment(
                id="voice-a",
                chapter_id="chapter-a",
                order=1,
                state=SegmentState.AUDIO_READY,
                planned_duration_seconds=8,
                actual_duration_seconds=8,
                audio_source_url="/api/audio/mock/narration/voice-a?duration=8",
                title="Voice",
                narration_text="Bridge",
            ),
            MusicSegment(
                id="music-b",
                chapter_id="chapter-b",
                order=2,
                state=SegmentState.AUDIO_READY,
                planned_duration_seconds=35,
                actual_duration_seconds=35,
                track_ref="track-b",
                audio_source_url="/api/audio/mock/music/b?duration=35",
                title="B",
                artist="Artist B",
            ),
        ],
        current_segment_id="music-a",
        last_activity_at=datetime.now(UTC),
        last_heartbeat_at=datetime.now(UTC),
    )
    repository.save(episode)
    yield episode
    api_module.repository, api_module.orchestrator, api_module.scheduler = old


def test_mix_plan_is_owned_deterministic_and_read_only(canonical_episode: LiveEpisode) -> None:
    client = TestClient(api_module.app)
    headers = {"X-Wavecast-Listener": "listener-a"}
    before = canonical_episode.model_dump(mode="json")

    first = client.get(
        f"/api/episodes/{canonical_episode.id}/mix-plan",
        headers=headers,
    )
    second = client.get(
        f"/api/episodes/{canonical_episode.id}/mix-plan",
        headers=headers,
    )

    assert first.status_code == 200
    assert first.json() == second.json()
    assert first.json()["schemaVersion"] == 1
    assert first.json()["episodeId"] == canonical_episode.id
    assert first.json()["clips"][0]["timelineStartSeconds"] == 0
    assert first.json()["clips"][0]["sourceUrl"].startswith("/api/")
    assert first.json()["clips"][0]["gainAutomation"]
    assert api_module.repository.get(canonical_episode.id).model_dump(mode="json") == before


def test_mix_plan_exposes_only_ready_prefix(canonical_episode: LiveEpisode) -> None:
    pending = canonical_episode.model_copy(deep=True)
    pending.segments[2] = pending.segments[2].model_copy(update={"state": SegmentState.PLANNED})
    api_module.repository.save(pending)

    client = TestClient(api_module.app)
    endpoint = f"/api/episodes/{canonical_episode.id}/mix-plan"
    headers = {"X-Wavecast-Listener": "listener-a"}

    prefix = client.get(endpoint, headers=headers)
    assert prefix.status_code == 200
    assert [clip["segmentId"] for clip in prefix.json()["clips"]] == ["music-a", "voice-a"]

    pending.segments[2] = pending.segments[2].model_copy(update={"state": SegmentState.AUDIO_READY})
    api_module.repository.save(pending)
    complete = client.get(endpoint, headers=headers)
    assert complete.status_code == 200
    assert [clip["segmentId"] for clip in complete.json()["clips"]] == [
        "music-a",
        "voice-a",
        "music-b",
    ]


def test_mix_plan_rejects_other_listener(canonical_episode: LiveEpisode) -> None:
    response = TestClient(api_module.app).get(
        f"/api/episodes/{canonical_episode.id}/mix-plan",
        headers={"X-Wavecast-Listener": "listener-b"},
    )
    assert response.status_code == 404
