"""Postgres persistence for user context."""

from __future__ import annotations

import asyncio
from typing import Any, cast

from sqlalchemy import Boolean, Column, DateTime, Index, String, Table, delete, select
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from wavecast.deployment import normalize_database_url
from wavecast.storage.schema import metadata
from wavecast.user_context import UserEvent, UserPreferences

user_preferences_table = Table(
    "user_preferences",
    metadata,
    Column("user_id", String(128), primary_key=True),
    Column("genres", JSONB, nullable=False),
    Column("artists", JSONB, nullable=False),
    Column("moods", JSONB, nullable=False),
    Column("contexts", JSONB, nullable=False),
    Column("discovery_level", String(32), nullable=False),
    Column("onboarding_completed", Boolean, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

user_events_table = Table(
    "user_events",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("user_id", String(128), nullable=False),
    Column("event_type", String(32), nullable=False),
    Column("program_id", String(128), nullable=True),
    Column("episode_id", String(128), nullable=True),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
)
Index(
    "ix_user_events_user_id_occurred_at",
    user_events_table.c.user_id,
    user_events_table.c.occurred_at,
)


class PostgresUserPreferencesRepository:
    def __init__(self, database_url: str) -> None:
        self.engine: AsyncEngine = create_async_engine(
            normalize_database_url(database_url), poolclass=NullPool
        )

    def get(self, user_id: str) -> UserPreferences | None:
        return cast(UserPreferences | None, self._run(self._get(user_id)))

    def save(self, preferences: UserPreferences) -> UserPreferences:
        self._run(self._save(preferences))
        return preferences

    def delete(self, user_id: str) -> bool:
        return cast(bool, self._run(self._delete(user_id)))

    def close(self) -> None:
        self._run(self.engine.dispose())

    @staticmethod
    def _run(coroutine: Any) -> Any:
        return asyncio.run(coroutine)

    async def _get(self, user_id: str) -> UserPreferences | None:
        async with self.engine.connect() as connection:
            row = (
                await connection.execute(
                    select(user_preferences_table).where(
                        user_preferences_table.c.user_id == user_id
                    )
                )
            ).first()
        return UserPreferences.model_validate(dict(row._mapping)) if row else None

    async def _save(self, preferences: UserPreferences) -> None:
        payload = preferences.model_dump(mode="json")
        values = {
            "user_id": preferences.user_id,
            "genres": payload["genres"],
            "artists": payload["artists"],
            "moods": payload["moods"],
            "contexts": payload["contexts"],
            "discovery_level": payload["discovery_level"],
            "onboarding_completed": preferences.onboarding_completed,
            "updated_at": preferences.updated_at,
        }
        statement = insert(user_preferences_table).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[user_preferences_table.c.user_id],
            set_={key: getattr(statement.excluded, key) for key in values if key != "user_id"},
        )
        async with self.engine.begin() as connection:
            await connection.execute(statement)

    async def _delete(self, user_id: str) -> bool:
        async with self.engine.begin() as connection:
            result = await connection.execute(
                delete(user_preferences_table).where(user_preferences_table.c.user_id == user_id)
            )
        return result.rowcount > 0


class PostgresUserEventRepository:
    def __init__(self, database_url: str) -> None:
        self.engine: AsyncEngine = create_async_engine(
            normalize_database_url(database_url), poolclass=NullPool
        )

    def create(self, event: UserEvent) -> UserEvent:
        self._run(self._create(event))
        return event

    def close(self) -> None:
        self._run(self.engine.dispose())

    @staticmethod
    def _run(coroutine: Any) -> Any:
        return asyncio.run(coroutine)

    async def _create(self, event: UserEvent) -> None:
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(user_events_table).values(
                    id=event.id,
                    user_id=event.user_id,
                    event_type=event.event_type.value,
                    program_id=event.program_id,
                    episode_id=event.episode_id,
                    occurred_at=event.occurred_at,
                )
            )
