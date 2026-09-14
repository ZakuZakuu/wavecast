import asyncio
import os

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from wavecast.models.episode import CoverParams, EpisodeSeed, GenerationMode, SegmentState
from wavecast.orchestration.episode import EpisodeOrchestrator
from wavecast.storage.episodes import PostgresEpisodeRepository, metadata

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
