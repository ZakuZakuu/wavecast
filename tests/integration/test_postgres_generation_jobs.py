from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import create_async_engine
from wavecast.storage.generation_jobs import (
    GenerationJobMode,
    GenerationJobStatus,
    PostgresGenerationJobRepository,
    generation_jobs_table,
)

DATABASE_URL = os.getenv("WAVECAST_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="set WAVECAST_TEST_DATABASE_URL to run Postgres integration tests"
)


def test_generation_job_survives_repository_reconstruction_and_requeues_newer_request() -> None:
    assert DATABASE_URL is not None
    episode_id = f"generation-job-{uuid4().hex}"

    async def remove_test_row() -> None:
        engine = create_async_engine(DATABASE_URL)
        async with engine.begin() as connection:
            await connection.execute(
                delete(generation_jobs_table).where(
                    generation_jobs_table.c.episode_id == episode_id
                )
            )
        await engine.dispose()

    asyncio.run(remove_test_row())
    first = PostgresGenerationJobRepository(DATABASE_URL)
    try:
        requested = first.request(episode_id)
        claimed = first.claim("worker-a", lease_seconds=120)
        assert claimed is not None
        assert claimed.id == requested.id
        assert claimed.status is GenerationJobStatus.RUNNING

        newer = first.request(episode_id, GenerationJobMode.FULL)
        assert newer.request_version == claimed.request_version + 1
        assert newer.mode is GenerationJobMode.FULL
    finally:
        first.close()

    second = PostgresGenerationJobRepository(DATABASE_URL)
    try:
        requeued = second.complete(
            claimed.id,
            "worker-a",
            claimed.request_version,
        )
        assert requeued.status is GenerationJobStatus.PENDING
        assert requeued.mode is GenerationJobMode.FULL

        claimed_again = second.claim("worker-b", lease_seconds=120)
        assert claimed_again is not None
        assert claimed_again.id == claimed.id
        assert claimed_again.lease_owner == "worker-b"
    finally:
        second.close()
        asyncio.run(remove_test_row())
