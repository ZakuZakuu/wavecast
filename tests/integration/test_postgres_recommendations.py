from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import create_async_engine
from wavecast.recommendations import ProgramIdea
from wavecast.storage.recommendations import (
    PostgresProgramIdeaRepository,
    program_ideas_table,
)

DATABASE_URL = os.getenv("WAVECAST_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="set WAVECAST_TEST_DATABASE_URL to run Postgres integration tests"
)


def test_program_ideas_are_durable_and_scoped_to_the_owner() -> None:
    assert DATABASE_URL is not None
    user_id = f"recommendation-test-{uuid4().hex}"
    idea = ProgramIdea(
        id=uuid4().hex,
        user_id=user_id,
        title="夜色里的 R&B",
        description="沿着偏好的风格继续探索。",
        reason="根据用户选择的 R&B 生成。",
        tags=["R&B", "Late Night"],
        created_at=datetime.now(UTC),
    )

    async def cleanup() -> None:
        engine = create_async_engine(DATABASE_URL)
        async with engine.begin() as connection:
            await connection.execute(
                delete(program_ideas_table).where(program_ideas_table.c.user_id == user_id)
            )
        await engine.dispose()

    asyncio.run(cleanup())
    first = PostgresProgramIdeaRepository(DATABASE_URL)
    first.save_many([idea])
    first.close()
    reopened = PostgresProgramIdeaRepository(DATABASE_URL)
    try:
        assert reopened.list_for_user(user_id) == [idea]
        assert reopened.list_for_user(f"{user_id}-other") == []
    finally:
        asyncio.run(cleanup())
        reopened.close()
