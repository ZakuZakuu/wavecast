from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Lock
from time import sleep
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import create_async_engine
from wavecast.recommendations import ProgramIdea, ProgramIdeaStatus
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


def test_concurrent_refreshes_use_database_cooldown_lock() -> None:
    assert DATABASE_URL is not None
    user_id = f"recommendation-lock-test-{uuid4().hex}"
    now = datetime.now(UTC)
    repositories = [PostgresProgramIdeaRepository(DATABASE_URL) for _ in range(2)]
    calls = 0
    calls_lock = Lock()

    def generate() -> list[ProgramIdea]:
        nonlocal calls
        with calls_lock:
            calls += 1
        sleep(0.05)
        return [
            ProgramIdea(
                id=uuid4().hex,
                user_id=user_id,
                title="并发刷新测试",
                description="测试同一冷却窗口只生成一次。",
                reason="Postgres advisory lock regression",
                created_at=now,
            )
        ]

    async def cleanup() -> None:
        engine = create_async_engine(DATABASE_URL)
        async with engine.begin() as connection:
            await connection.execute(
                delete(program_ideas_table).where(program_ideas_table.c.user_id == user_id)
            )
        await engine.dispose()

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda repository: repository.refresh_if_due(
                        user_id,
                        now=now,
                        refresh_interval=timedelta(hours=24),
                        generate=generate,
                    ),
                    repositories,
                )
            )
        assert calls == 1
        assert results[0] == results[1]
    finally:
        asyncio.run(cleanup())
        for repository in repositories:
            repository.close()


def test_refresh_generator_can_run_sync_async_facades() -> None:
    assert DATABASE_URL is not None
    user_id = f"recommendation-nested-loop-test-{uuid4().hex}"
    now = datetime.now(UTC)
    repository = PostgresProgramIdeaRepository(DATABASE_URL)

    def generate() -> list[ProgramIdea]:
        # Recommendation generation reads through synchronous repository facades
        # that internally use asyncio.run(). This must not execute on the
        # Postgres refresh event loop.
        asyncio.run(asyncio.sleep(0))
        return [
            ProgramIdea(
                id=uuid4().hex,
                user_id=user_id,
                title="事件循环回归测试",
                description="验证生成阶段可以安全读取同步异步仓储。",
                reason="nested asyncio.run regression",
                created_at=now,
            )
        ]

    async def cleanup() -> None:
        engine = create_async_engine(DATABASE_URL)
        async with engine.begin() as connection:
            await connection.execute(
                delete(program_ideas_table).where(program_ideas_table.c.user_id == user_id)
            )
        await engine.dispose()

    asyncio.run(cleanup())
    try:
        ideas = repository.refresh_if_due(
            user_id,
            now=now,
            refresh_interval=timedelta(hours=24),
            generate=generate,
        )
        assert len(ideas) == 1
        assert ideas[0].user_id == user_id
    finally:
        repository.close()
        asyncio.run(cleanup())


def test_program_idea_status_transition_is_owner_scoped_and_single_use() -> None:
    assert DATABASE_URL is not None
    user_id = f"recommendation-status-test-{uuid4().hex}"
    other_user = f"{user_id}-other"
    idea = ProgramIdea(
        id=uuid4().hex,
        user_id=user_id,
        title="状态转换测试",
        description="验证推荐只能被拥有者原子消费一次。",
        reason="Postgres status transition regression",
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
    repository = PostgresProgramIdeaRepository(DATABASE_URL)
    try:
        repository.save_many([idea])
        assert (
            repository.transition_status(
                other_user,
                idea.id,
                from_status=ProgramIdeaStatus.AVAILABLE,
                to_status=ProgramIdeaStatus.USED,
            )
            is None
        )
        claimed = repository.transition_status(
            user_id,
            idea.id,
            from_status=ProgramIdeaStatus.AVAILABLE,
            to_status=ProgramIdeaStatus.USED,
        )
        assert claimed is not None
        assert claimed.status is ProgramIdeaStatus.USED
        assert (
            repository.transition_status(
                user_id,
                idea.id,
                from_status=ProgramIdeaStatus.AVAILABLE,
                to_status=ProgramIdeaStatus.USED,
            )
            is None
        )
        assert repository.get_for_user(user_id, idea.id) == claimed
    finally:
        repository.close()
        asyncio.run(cleanup())
