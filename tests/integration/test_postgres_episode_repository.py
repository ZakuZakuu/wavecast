import asyncio
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine
from wavecast.models.episode import (
    CoverParams,
    EpisodeSeed,
    EpisodeState,
    GenerationMode,
    LiveEpisode,
    SegmentState,
)
from wavecast.orchestration.episode import EpisodeOrchestrator
from wavecast.storage import EpisodeConcurrencyError
from wavecast.storage.episodes import PostgresEpisodeRepository, metadata

from tests.test_staged_intelligence import _session

DATABASE_URL = os.getenv("WAVECAST_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="set WAVECAST_TEST_DATABASE_URL to run Postgres integration tests"
)


def postgres_seed() -> EpisodeSeed:
    return EpisodeSeed(
        id="postgres-seed",
        title="Postgres",
        topic="Durability",
        short_description="Test",
        estimated_duration_seconds=1800,
        opening_track_ref="mock:opening",
        opening_track_title="Opening",
        opening_track_artist="Artist",
        cover=CoverParams(family="editorial", seed=2, palette=("#000", "#fff")),
    )


def test_postgres_recovers_seek_skip_and_materialization_after_reconstruction() -> None:
    assert DATABASE_URL is not None

    async def reset_schema() -> None:
        engine = create_async_engine(DATABASE_URL)
        async with engine.begin() as connection:
            await connection.run_sync(metadata.drop_all)
            await connection.run_sync(metadata.create_all)
        await engine.dispose()

    asyncio.run(reset_schema())
    first_repository = PostgresEpisodeRepository(DATABASE_URL)
    first = EpisodeOrchestrator(first_repository)
    episode = first.start_or_resume(postgres_seed(), "postgres-listener")
    first.seek(episode.id, 5)
    buffered = first.ensure_buffer(episode.id, target_chapters=1, target_ahead_seconds=300)
    buffered.segment("segment-narration-1").state = SegmentState.SCRIPT_READY
    first_repository.save(buffered)
    first.next_playable(episode.id)
    first.materialize_all(episode.id)
    first_repository.close()

    recovered_repository = PostgresEpisodeRepository(DATABASE_URL)
    recovered = EpisodeOrchestrator(recovered_repository)
    restored = recovered.start_or_resume(postgres_seed(), "postgres-listener")

    assert restored.id == episode.id
    assert restored.playback_position_seconds > 0
    assert restored.generation_mode is GenerationMode.FULL
    assert restored.segment("segment-narration-1").state is SegmentState.SKIPPED
    assert restored.version > episode.version
    recovered_repository.close()


def test_postgres_compare_and_swap_rejects_stale_snapshot() -> None:
    assert DATABASE_URL is not None
    repository = PostgresEpisodeRepository(DATABASE_URL)
    orchestrator = EpisodeOrchestrator(repository)
    episode = orchestrator.start_or_resume(postgres_seed(), "cas-listener")
    first = repository.get(episode.id)
    stale = repository.get(episode.id)

    first.state = EpisodeState.MATERIALIZED
    repository.save(first)

    stale.state = EpisodeState.STREAMING
    with pytest.raises(EpisodeConcurrencyError):
        repository.save(stale)

    reloaded = repository.get(episode.id)
    assert reloaded.state is EpisodeState.MATERIALIZED
    assert reloaded.version == first.version
    repository.close()


def test_postgres_backed_sse_endpoint_reads_in_a_worker_thread() -> None:
    assert DATABASE_URL is not None
    import services.api.main as api_module

    repository = PostgresEpisodeRepository(DATABASE_URL)
    previous = api_module.repository
    api_module.configure_runtime(repository)
    try:
        client = TestClient(api_module.app)
        headers = {"X-Wavecast-Listener": "postgres-sse-listener"}
        episode = client.post(
            "/api/episodes/from-seed/city-pop-misunderstood", headers=headers
        ).json()
        with client.stream(
            "GET", f"/api/episodes/{episode['id']}/events?once=true", headers=headers
        ) as response:
            lines = list(response.iter_lines())
        assert response.status_code == 200
        assert any(line == "event: episode_state_changed" for line in lines)
    finally:
        api_module.configure_runtime(previous)
        repository.close()


def test_postgres_round_trips_typed_progressive_session_and_legacy_payload() -> None:
    assert DATABASE_URL is not None
    repository = PostgresEpisodeRepository(DATABASE_URL)
    first = EpisodeOrchestrator(repository)
    episode = first.start_or_resume(postgres_seed(), "progressive-session-listener")
    episode.progressive_session = _session()
    repository.save(episode)

    restored = repository.get(episode.id)
    assert restored.progressive_session is not None
    assert restored.progressive_session.schema_version == 1

    legacy = restored.model_dump(mode="json")
    assert "progressive_session" not in legacy
    assert LiveEpisode.model_validate(legacy).progressive_session is None
    repository.close()
