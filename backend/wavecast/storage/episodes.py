"""Repository implementations; persistence never owns runtime decisions."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, Protocol, cast

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from wavecast.deployment import normalize_database_url
from wavecast.models.episode import LiveEpisode
from wavecast.storage.schema import metadata


class EpisodeNotFoundError(KeyError):
    pass


class EpisodeConcurrencyError(RuntimeError):
    """The supplied snapshot was superseded and must be reloaded before retrying."""


class EpisodeRepository(Protocol):
    def save(self, episode: LiveEpisode) -> LiveEpisode: ...

    def get(self, episode_id: str) -> LiveEpisode: ...

    def find_by_listener_seed(self, listener_id: str, seed_id: str) -> LiveEpisode | None: ...

    def find_by_user_seed(self, user_id: str, seed_id: str) -> LiveEpisode | None: ...

    def claim_user(self, episode_id: str, listener_id: str, user_id: str) -> bool: ...

    def owned_by_user(self, episode_id: str, user_id: str) -> bool: ...

    def all(self) -> list[LiveEpisode]: ...


episodes_table = Table(
    "episodes",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("listener_id", String(128), nullable=False),
    Column("owner_user_id", String(128), nullable=True),
    Column("seed_id", String(128), nullable=False),
    Column("version", Integer, nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("listener_id", "seed_id", name="uq_episodes_listener_seed"),
)
Index("ix_episodes_owner_user_id", episodes_table.c.owner_user_id)
Index(
    "uq_episodes_owner_user_seed", episodes_table.c.owner_user_id, episodes_table.c.seed_id,
    unique=True, postgresql_where=episodes_table.c.owner_user_id.is_not(None),
)


def _episode_from_row(row: Any) -> LiveEpisode:
    episode = LiveEpisode.model_validate(row.payload)
    return episode.model_copy(update={"owner_user_id": row.owner_user_id})


class PostgresEpisodeRepository:
    """Postgres source-of-truth repository using SQLAlchemy's asyncpg dialect.

    The deterministic Phase 1 orchestrator is deliberately synchronous. This adapter
    bridges that boundary with a short-lived event loop and ``NullPool``: no async DB
    connection is retained across request threads/loops. A later async worker can use
    the same schema directly without changing episode payload semantics.
    """

    def __init__(self, database_url: str) -> None:
        self.engine: AsyncEngine = create_async_engine(
            normalize_database_url(database_url), poolclass=NullPool
        )

    def save(self, episode: LiveEpisode) -> LiveEpisode:
        next_version = episode.version + 1
        self._run(self._save(episode, next_version))
        episode.version = next_version
        return episode

    def get(self, episode_id: str) -> LiveEpisode:
        episode = cast(LiveEpisode | None, self._run(self._get(episode_id)))
        if episode is None:
            raise EpisodeNotFoundError(episode_id)
        return episode

    def find_by_listener_seed(self, listener_id: str, seed_id: str) -> LiveEpisode | None:
        return cast(
            LiveEpisode | None, self._run(self._find_by_listener_seed(listener_id, seed_id))
        )

    def find_by_user_seed(self, user_id: str, seed_id: str) -> LiveEpisode | None:
        return cast(LiveEpisode | None, self._run(self._find_by_user_seed(user_id, seed_id)))

    def claim_user(self, episode_id: str, listener_id: str, user_id: str) -> bool:
        return bool(self._run(self._claim_user(episode_id, listener_id, user_id)))

    def owned_by_user(self, episode_id: str, user_id: str) -> bool:
        return bool(self._run(self._owned_by_user(episode_id, user_id)))

    def all(self) -> list[LiveEpisode]:
        return cast(list[LiveEpisode], self._run(self._all()))

    def close(self) -> None:
        self._run(self.engine.dispose())

    @staticmethod
    def _run(coroutine: Any) -> Any:
        return asyncio.run(coroutine)

    async def _save(self, episode: LiveEpisode, next_version: int) -> None:
        payload = episode.model_copy(update={"version": next_version}).model_dump(mode="json")
        if episode.progressive_session is not None:
            payload["progressive_session"] = episode.progressive_session.model_dump(mode="json")
        values = dict(
            id=episode.id,
            listener_id=episode.listener_id,
            owner_user_id=episode.owner_user_id,
            seed_id=episode.seed_id,
            version=next_version,
            payload=payload,
            updated_at=datetime.now(UTC),
        )
        async with self.engine.begin() as connection:
            if episode.version == 0:
                result = await connection.execute(
                    insert(episodes_table).values(**values).on_conflict_do_nothing()
                )
            else:
                update_values = dict(values)
                statement = episodes_table.update().where(
                    episodes_table.c.id == episode.id,
                    episodes_table.c.version == episode.version,
                )
                if episode.owner_user_id is None:
                    # A stale guest snapshot must not clear a claim made after it was loaded.
                    update_values.pop("owner_user_id")
                else:
                    statement = statement.where(
                        (episodes_table.c.owner_user_id.is_(None))
                        | (episodes_table.c.owner_user_id == episode.owner_user_id)
                    )
                result = await connection.execute(
                    statement.values(**update_values)
                )
            if result.rowcount != 1:
                raise EpisodeConcurrencyError(f"stale episode snapshot: {episode.id}")

    async def _get(self, episode_id: str) -> LiveEpisode | None:
        async with self.engine.connect() as connection:
            row = (
                await connection.execute(
                    select(episodes_table.c.payload, episodes_table.c.owner_user_id).where(episodes_table.c.id == episode_id)
                )
            ).first()
        return _episode_from_row(row) if row else None

    async def _find_by_listener_seed(self, listener_id: str, seed_id: str) -> LiveEpisode | None:
        statement = select(episodes_table.c.payload, episodes_table.c.owner_user_id).where(
            episodes_table.c.listener_id == listener_id,
            episodes_table.c.seed_id == seed_id,
        )
        async with self.engine.connect() as connection:
            row = (await connection.execute(statement)).first()
        return _episode_from_row(row) if row else None

    async def _find_by_user_seed(self, user_id: str, seed_id: str) -> LiveEpisode | None:
        statement = select(episodes_table.c.payload, episodes_table.c.owner_user_id).where(
            episodes_table.c.owner_user_id == user_id,
            episodes_table.c.seed_id == seed_id,
        )
        async with self.engine.connect() as connection:
            row = (await connection.execute(statement)).first()
        return _episode_from_row(row) if row else None

    async def _claim_user(self, episode_id: str, listener_id: str, user_id: str) -> bool:
        try:
            async with self.engine.begin() as connection:
                result = await connection.execute(
                    update(episodes_table)
                    .where(
                        episodes_table.c.id == episode_id,
                        episodes_table.c.listener_id == listener_id,
                        (episodes_table.c.owner_user_id.is_(None))
                        | (episodes_table.c.owner_user_id == user_id),
                    )
                    .values(owner_user_id=user_id)
                )
            return result.rowcount == 1
        except IntegrityError:
            # Another episode for this same seed is already owned by the account.
            return False

    async def _owned_by_user(self, episode_id: str, user_id: str) -> bool:
        async with self.engine.connect() as connection:
            value = await connection.scalar(
                select(episodes_table.c.id).where(
                    episodes_table.c.id == episode_id, episodes_table.c.owner_user_id == user_id
                )
            )
        return value is not None

    async def _all(self) -> list[LiveEpisode]:
        async with self.engine.connect() as connection:
            rows = (await connection.execute(select(episodes_table.c.payload, episodes_table.c.owner_user_id))).all()
        return [_episode_from_row(row) for row in rows]
