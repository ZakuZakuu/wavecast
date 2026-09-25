"""Postgres persistence for authenticated recommendation candidates."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Any, cast

from sqlalchemy import Column, DateTime, Index, String, Table, desc, select
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from wavecast.deployment import normalize_database_url
from wavecast.recommendations import ProgramIdea, ProgramIdeaRepository
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

    async def _list_for_user(self, user_id: str, limit: int) -> list[ProgramIdea]:
        async with self.engine.connect() as connection:
            rows = (
                await connection.execute(
                    select(program_ideas_table.c.payload)
                    .where(program_ideas_table.c.user_id == user_id)
                    .order_by(desc(program_ideas_table.c.created_at))
                    .limit(limit)
                )
            ).all()
        return [ProgramIdea.model_validate(row.payload) for row in rows]
