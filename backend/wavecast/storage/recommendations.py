"""Postgres persistence for authenticated recommendation candidates."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from threading import RLock
from typing import Any, cast

from sqlalchemy import Column, DateTime, Index, String, Table, delete, desc, func, select, update
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from wavecast.deployment import normalize_database_url
from wavecast.recommendations import (
    MAX_LISTED_IDEAS_PER_USER,
    MAX_STORED_IDEAS_PER_USER,
    MIN_AVAILABLE_IDEAS_PER_USER,
    ProgramIdea,
    ProgramIdeaRepository,
    ProgramIdeaStatus,
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
        self._run_lock = RLock()

    def save_many(self, ideas: Iterable[ProgramIdea]) -> None:
        self._run(self._save_many(list(ideas)))

    def list_for_user(self, user_id: str, *, limit: int = 12) -> list[ProgramIdea]:
        return cast(list[ProgramIdea], self._run(self._list_for_user(user_id, limit)))

    def get_for_user(self, user_id: str, idea_id: str) -> ProgramIdea | None:
        return cast(ProgramIdea | None, self._run(self._get_for_user(user_id, idea_id)))

    def transition_status(
        self,
        user_id: str,
        idea_id: str,
        *,
        from_status: ProgramIdeaStatus,
        to_status: ProgramIdeaStatus,
    ) -> ProgramIdea | None:
        return cast(
            ProgramIdea | None,
            self._run(
                self._transition_status(
                    user_id,
                    idea_id,
                    from_status=from_status,
                    to_status=to_status,
                )
            ),
        )

    def refresh_if_due(
        self,
        user_id: str,
        *,
        now: datetime,
        refresh_interval: timedelta,
        source: str,
        generate: Callable[[], list[ProgramIdea]],
    ) -> list[ProgramIdea]:
        return cast(
            list[ProgramIdea],
            self._run(
                self._refresh_if_due(
                    user_id,
                    now,
                    refresh_interval,
                    source,
                    generate,
                )
            ),
        )

    def close(self) -> None:
        self._run(self.engine.dispose())

    def _run(self, coroutine: Any) -> Any:
        with self._run_lock:
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
        source: str,
        generate: Callable[[], list[ProgramIdea]],
    ) -> list[ProgramIdea]:
        async with self.engine.begin() as connection:
            # A transaction-scoped per-user lock makes the cooldown check + write atomic
            # across API workers. hashtext collisions only serialize unrelated users.
            await connection.execute(
                select(func.pg_advisory_xact_lock(1330667079, func.hashtext(user_id)))
            )
            rows = (
                await connection.execute(
                    select(
                        program_ideas_table.c.created_at,
                        program_ideas_table.c.payload,
                    )
                    .where(program_ideas_table.c.user_id == user_id)
                    .order_by(
                        desc(program_ideas_table.c.created_at),
                        desc(program_ideas_table.c.id),
                    )
                    .limit(MAX_LISTED_IDEAS_PER_USER)
                )
            ).all()
            existing = [ProgramIdea.model_validate(row.payload) for row in rows]
            same_source = [idea for idea in existing if idea.source == source]
            available = [
                idea
                for idea in same_source
                if idea.status is ProgramIdeaStatus.AVAILABLE
            ]
            latest = same_source[0].created_at if same_source else None
            has_consumed = any(
                idea.status is not ProgramIdeaStatus.AVAILABLE for idea in same_source
            )
            if (
                latest is not None
                and now - latest < refresh_interval
                and (
                    len(available) >= MIN_AVAILABLE_IDEAS_PER_USER
                    or not has_consumed
                )
            ):
                return available

            # The recommendation generator is synchronous and may call other
            # sync repository facades that use asyncio.run(). Keep it outside
            # this repository's running event loop while retaining the
            # transaction-scoped advisory lock and single-generator semantics.
            ideas = await asyncio.to_thread(generate)
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
            combined = [*ideas, *available]
            return sorted(
                combined,
                key=lambda idea: (idea.created_at, idea.id),
                reverse=True,
            )[:MAX_LISTED_IDEAS_PER_USER]

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

    async def _get_for_user(self, user_id: str, idea_id: str) -> ProgramIdea | None:
        async with self.engine.connect() as connection:
            row = (
                await connection.execute(
                    select(program_ideas_table.c.payload).where(
                        program_ideas_table.c.id == idea_id,
                        program_ideas_table.c.user_id == user_id,
                    )
                )
            ).first()
        return ProgramIdea.model_validate(row.payload) if row else None

    async def _transition_status(
        self,
        user_id: str,
        idea_id: str,
        *,
        from_status: ProgramIdeaStatus,
        to_status: ProgramIdeaStatus,
    ) -> ProgramIdea | None:
        async with self.engine.begin() as connection:
            row = (
                await connection.execute(
                    select(program_ideas_table.c.payload)
                    .where(
                        program_ideas_table.c.id == idea_id,
                        program_ideas_table.c.user_id == user_id,
                    )
                    .with_for_update()
                )
            ).first()
            if row is None:
                return None
            current = ProgramIdea.model_validate(row.payload)
            if current.status is not from_status:
                return None
            updated = current.model_copy(update={"status": to_status})
            await connection.execute(
                update(program_ideas_table)
                .where(
                    program_ideas_table.c.id == idea_id,
                    program_ideas_table.c.user_id == user_id,
                )
                .values(payload=updated.model_dump(mode="json"))
            )
            return updated
