"""Postgres persistence for authenticated recommendation candidates."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import Column, DateTime, Index, String, Table, delete, desc, func, select
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from wavecast.deployment import normalize_database_url
from wavecast.recommendations import (
    MAX_LISTED_IDEAS_PER_USER,
    MAX_STORED_IDEAS_PER_USER,
    ProgramIdea,
    ProgramIdeaRepository,
)
from wavecast.storage.schema import metadata

program_ideas_table = Table(
    "program_ideas",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("user_id", String(128), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("payload", JSONB, nullable=False),
)
Index(
    "ix_program_ideas_user_id_created_at",
    program_ideas_table.c.user_id,
    program_ideas_table.c.created_at,
)


class PostgresProgramIdeaRepository(ProgramIdeaRepository):
    def __init__(self, database_url: str) -> None:
        self.engine: AsyncEngine = create_async_engine(
            normalize_database_url(database_url), poolclass=NullPool
        )

    def save_many(self, ideas: Iterable[ProgramIdea]) -> None:
        self._run(self._save_many(list(ideas)))

    def list_for_user(self, user_id: str, *, limit: int = 12) -> list[ProgramIdea]:
        return cast(list[ProgramIdea], self._run(self._list_for_user(user_id, limit)))

    def refresh_if_due(
        self,
        user_id: str,
        *,
        now: datetime,
        refresh_interval: timedelta,
        generate: Callable[[], list[ProgramIdea]],
    ) -> list[ProgramIdea]:
        return cast(
            list[ProgramIdea],
            self._run(self._refresh_if_due(user_id, now, refresh_interval, generate)),
        )

    def close(self) -> None:
        self._run(self.engine.dispose())

    @staticmethod
    def _run(coroutine: Any) -> Any:
        return asyncio.run(coroutine)

    async def _save_many(self, ideas: list[ProgramIdea]) -> None:
        if not ideas:
            return
        rows = [
            {
                "id": idea.id,
                "user_id": idea.user_id,
                "created_at": idea.created_at,
                "payload": idea.model_dump(mode="json"),
            }
            for idea in ideas
        ]
        statement = insert(program_ideas_table).values(rows)
        statement = statement.on_conflict_do_update(
            index_elements=[program_ideas_table.c.id],
            set_={
                "user_id": statement.excluded.user_id,
                "created_at": statement.excluded.created_at,
                "payload": statement.excluded.payload,
            },
        )
        async with self.engine.begin() as connection:
            await connection.execute(statement)
            for user_id in {idea.user_id for idea in ideas}:
                await self._prune_user(connection, user_id=user_id)

    async def _refresh_if_due(
        self,
        user_id: str,
        now: datetime,
        refresh_interval: timedelta,
        generate: Callable[[], list[ProgramIdea]],
    ) -> list[ProgramIdea]:
        async with self.engine.begin() as connection:
            # A transaction-scoped per-user lock makes the cooldown check + write atomic
            # across API workers. hashtext collisions only serialize unrelated users.
            await connection.execute(
                select(func.pg_advisory_xact_lock(1330667079, func.hashtext(user_id)))
            )
            latest = await connection.scalar(
                select(program_ideas_table.c.created_at)
                .where(program_ideas_table.c.user_id == user_id)
                .order_by(desc(program_ideas_table.c.created_at), desc(program_ideas_table.c.id))
                .limit(1)
            )
            if latest is not None and now - latest < refresh_interval:
                rows = (
                    await connection.execute(
                        select(program_ideas_table.c.payload)
                        .where(program_ideas_table.c.user_id == user_id)
                        .order_by(
                            desc(program_ideas_table.c.created_at), desc(program_ideas_table.c.id)
                        )
                        .limit(MAX_LISTED_IDEAS_PER_USER)
                    )
                ).all()
                return [ProgramIdea.model_validate(row.payload) for row in rows]

            ideas = generate()
            if ideas:
                statement = insert(program_ideas_table).values(
                    [
                        {
                            "id": idea.id,
                            "user_id": idea.user_id,
                            "created_at": idea.created_at,
                            "payload": idea.model_dump(mode="json"),
                        }
                        for idea in ideas
                    ]
                )
                await connection.execute(statement)
                await self._prune_user(connection, user_id=user_id)
            return ideas

    @staticmethod
    async def _prune_user(connection: Any, *, user_id: str) -> None:
        retained_ids = (
            select(program_ideas_table.c.id)
            .where(program_ideas_table.c.user_id == user_id)
            .order_by(desc(program_ideas_table.c.created_at), desc(program_ideas_table.c.id))
            .limit(MAX_STORED_IDEAS_PER_USER)
        )
        await connection.execute(
            delete(program_ideas_table).where(
                program_ideas_table.c.user_id == user_id,
                program_ideas_table.c.id.not_in(retained_ids),
            )
        )

    async def _list_for_user(self, user_id: str, limit: int) -> list[ProgramIdea]:
        async with self.engine.connect() as connection:
            rows = (
                await connection.execute(
                    select(program_ideas_table.c.payload)
                    .where(program_ideas_table.c.user_id == user_id)
                    .order_by(desc(program_ideas_table.c.created_at), desc(program_ideas_table.c.id))
                    .limit(limit)
                )
            ).all()
        return [ProgramIdea.model_validate(row.payload) for row in rows]
