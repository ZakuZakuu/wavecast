"""Storage for published programmes and who has listened to them."""

from __future__ import annotations

import asyncio
from collections.abc import Collection
from datetime import datetime
from threading import RLock
from typing import Any, Protocol, cast

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Table,
    and_,
    func,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from wavecast.deployment import normalize_database_url
from wavecast.publishing import (
    PINNING_STATUSES,
    Publication,
    PublicationStatus,
    Visibility,
    utc_now,
)
from wavecast.storage.schema import metadata

_UNSET: Any = object()


class PublicationConflictError(RuntimeError):
    """The episode already has a publication."""


class PublicationRepository(Protocol):
    def create(self, publication: Publication) -> Publication:
        """Raises PublicationConflictError when the episode already has one."""
        ...

    def get(self, publication_id: str) -> Publication | None: ...

    def get_by_code(self, code: str) -> Publication | None: ...

    def get_for_episode(self, episode_id: str) -> Publication | None: ...

    def update(
        self,
        publication_id: str,
        *,
        only_from: Collection[PublicationStatus] | None = None,
        **fields: Any,
    ) -> Publication | None:
        """Applies the given fields (`status`, `visibility`, `asset_keys`, `bytes_total`,
        `audio_seconds`, `plan_fingerprint`, `error_code`, `published_at`, `revoked_at`).

        None when the record is gone or not in an `only_from` status. The status condition is
        checked in the same step as the write, so two workers cannot both move a publication out of
        the same state.
        """
        ...

    def list_for_owner(self, listener_id: str, user_id: str | None) -> list[Publication]: ...

    def count_for_owner(
        self, listener_id: str, user_id: str | None, statuses: Collection[PublicationStatus],
    ) -> int: ...

    def count_status(self, statuses: Collection[PublicationStatus]) -> int: ...

    def pinned_episode_ids(self) -> set[str]:
        """Source episodes whose audio must not be reclaimed."""
        ...

    def pinned_bytes(self) -> int: ...

    def record_listen(self, publication_id: str, listener_key: str, at: datetime | None = None) -> bool:
        """True when this listener had not been counted for the programme before."""
        ...

    def listen_count(self, publication_id: str) -> int: ...

    def list_public(self, limit: int) -> list[Publication]:
        """Published programmes anyone may be shown (visibility `PUBLIC`), newest first."""
        ...

    def listens_since(self, publication_ids: Collection[str], since: datetime) -> dict[str, list[datetime]]:
        """When each listener first played each of the programmes, from `since` on."""
        ...


def _owned_by(publication: Publication, listener_id: str, user_id: str | None) -> bool:
    return publication.owner_listener_id == listener_id or (
        user_id is not None and publication.owner_user_id == user_id
    )


_FIELDS = (
    "status", "visibility", "asset_keys", "bytes_total", "audio_seconds", "plan_fingerprint",
    "error_code", "published_at", "revoked_at",
)


class InMemoryPublicationRepository:
    def __init__(self) -> None:
        self._by_id: dict[str, Publication] = {}
        self._listens: dict[tuple[str, str], datetime] = {}
        self._lock = RLock()

    def create(self, publication: Publication) -> Publication:
        with self._lock:
            if any(item.source_episode_id == publication.source_episode_id for item in self._by_id.values()):
                raise PublicationConflictError(publication.source_episode_id)
            self._by_id[publication.id] = publication.model_copy(deep=True)
            return publication.model_copy(deep=True)

    def get(self, publication_id: str) -> Publication | None:
        with self._lock:
            item = self._by_id.get(publication_id)
            return item.model_copy(deep=True) if item else None

    def get_by_code(self, code: str) -> Publication | None:
        with self._lock:
            for item in self._by_id.values():
                if item.code == code:
                    return item.model_copy(deep=True)
            return None

    def get_for_episode(self, episode_id: str) -> Publication | None:
        with self._lock:
            for item in self._by_id.values():
                if item.source_episode_id == episode_id:
                    return item.model_copy(deep=True)
            return None

    def update(
        self,
        publication_id: str,
        *,
        only_from: Collection[PublicationStatus] | None = None,
        **fields: Any,
    ) -> Publication | None:
        unknown = set(fields) - set(_FIELDS)
        if unknown:
            raise TypeError(f"unknown publication fields: {sorted(unknown)}")
        with self._lock:
            current = self._by_id.get(publication_id)
            if current is None or (only_from is not None and current.status not in only_from):
                return None
            changes = {key: value for key, value in fields.items() if value is not _UNSET}
            updated = current.model_copy(update={**changes, "updated_at": utc_now()})
            self._by_id[publication_id] = updated
            return updated.model_copy(deep=True)

    def list_for_owner(self, listener_id: str, user_id: str | None) -> list[Publication]:
        with self._lock:
            return [
                item.model_copy(deep=True) for item in self._by_id.values()
                if _owned_by(item, listener_id, user_id)
            ]

    def count_for_owner(
        self, listener_id: str, user_id: str | None, statuses: Collection[PublicationStatus],
    ) -> int:
        with self._lock:
            return sum(
                1 for item in self._by_id.values()
                if item.status in statuses and _owned_by(item, listener_id, user_id)
            )

    def count_status(self, statuses: Collection[PublicationStatus]) -> int:
        with self._lock:
            return sum(1 for item in self._by_id.values() if item.status in statuses)

    def pinned_episode_ids(self) -> set[str]:
        with self._lock:
            return {item.source_episode_id for item in self._by_id.values() if item.pins_audio}

    def pinned_bytes(self) -> int:
        with self._lock:
            return sum(item.bytes_total for item in self._by_id.values() if item.pins_audio)

    def record_listen(self, publication_id: str, listener_key: str, at: datetime | None = None) -> bool:
        with self._lock:
            key = (publication_id, listener_key)
            if key in self._listens:
                return False
            self._listens[key] = at or utc_now()
            return True

    def list_public(self, limit: int) -> list[Publication]:
        with self._lock:
            items = [
                item for item in self._by_id.values()
                if item.status is PublicationStatus.PUBLISHED and item.visibility is Visibility.PUBLIC
            ]
            items.sort(key=lambda item: item.published_at or item.created_at, reverse=True)
            return [item.model_copy(deep=True) for item in items[:limit]]

    def listens_since(self, publication_ids: Collection[str], since: datetime) -> dict[str, list[datetime]]:
        wanted = set(publication_ids)
        with self._lock:
            found: dict[str, list[datetime]] = {}
            for (publication_id, _key), at in self._listens.items():
                if publication_id in wanted and at >= since:
                    found.setdefault(publication_id, []).append(at)
            return found

    def listen_count(self, publication_id: str) -> int:
        with self._lock:
            return sum(1 for item_id, _ in self._listens if item_id == publication_id)


published_programmes_table = Table(
    "published_programmes",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("code", String(16), nullable=False, unique=True),
    Column("source_episode_id", String(64), nullable=False, unique=True),
    Column("owner_listener_id", String(128), nullable=False),
    Column("owner_user_id", String(128), nullable=True),
    Column("status", String(16), nullable=False),
    Column("visibility", String(16), nullable=False),
    Column("programme", JSONB, nullable=False),
    Column("asset_keys", JSONB, nullable=False),
    Column("bytes_total", BigInteger, nullable=False),
    Column("audio_seconds", Float, nullable=False),
    Column("plan_fingerprint", String(128), nullable=True),
    Column("error_code", String(64), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("published_at", DateTime(timezone=True), nullable=True),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
)
Index("ix_published_programmes_owner_user", published_programmes_table.c.owner_user_id)
Index("ix_published_programmes_owner_listener", published_programmes_table.c.owner_listener_id)
Index(
    "ix_published_programmes_status_visibility",
    published_programmes_table.c.status,
    published_programmes_table.c.visibility,
    published_programmes_table.c.published_at,
)

programme_listens_table = Table(
    "programme_listens",
    metadata,
    Column(
        "publication_id", String(64), ForeignKey("published_programmes.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("listener_key", String(160), primary_key=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


def _publication_from_row(row: Any) -> Publication:
    return Publication.model_validate(dict(row))


class PostgresPublicationRepository:
    def __init__(self, database_url: str) -> None:
        self.engine: AsyncEngine = create_async_engine(
            normalize_database_url(database_url), poolclass=NullPool
        )
        self._run_lock = RLock()

    def close(self) -> None:
        self._run(self.engine.dispose())

    def _run(self, coroutine: Any) -> Any:
        with self._run_lock:
            return asyncio.run(coroutine)

    def create(self, publication: Publication) -> Publication:
        return cast(Publication, self._run(self._create(publication)))

    def get(self, publication_id: str) -> Publication | None:
        return cast(Publication | None, self._run(self._one(published_programmes_table.c.id == publication_id)))

    def get_by_code(self, code: str) -> Publication | None:
        return cast(Publication | None, self._run(self._one(published_programmes_table.c.code == code)))

    def get_for_episode(self, episode_id: str) -> Publication | None:
        return cast(
            Publication | None,
            self._run(self._one(published_programmes_table.c.source_episode_id == episode_id)),
        )

    def update(
        self,
        publication_id: str,
        *,
        only_from: Collection[PublicationStatus] | None = None,
        **fields: Any,
    ) -> Publication | None:
        unknown = set(fields) - set(_FIELDS)
        if unknown:
            raise TypeError(f"unknown publication fields: {sorted(unknown)}")
        return cast(
            Publication | None,
            self._run(self._update(publication_id, only_from, {k: v for k, v in fields.items() if v is not _UNSET})),
        )

    def list_for_owner(self, listener_id: str, user_id: str | None) -> list[Publication]:
        return cast(list[Publication], self._run(self._list(self._owner_clause(listener_id, user_id))))

    def count_for_owner(
        self, listener_id: str, user_id: str | None, statuses: Collection[PublicationStatus],
    ) -> int:
        return cast(int, self._run(self._count(and_(
            published_programmes_table.c.status.in_([s.value for s in statuses]),
            self._owner_clause(listener_id, user_id),
        ))))

    def count_status(self, statuses: Collection[PublicationStatus]) -> int:
        return cast(int, self._run(self._count(
            published_programmes_table.c.status.in_([s.value for s in statuses]),
        )))

    def pinned_episode_ids(self) -> set[str]:
        return cast(set[str], self._run(self._pinned_ids()))

    def pinned_bytes(self) -> int:
        return cast(int, self._run(self._pinned_bytes()))

    def record_listen(self, publication_id: str, listener_key: str, at: datetime | None = None) -> bool:
        return cast(bool, self._run(self._record_listen(publication_id, listener_key, at)))

    def list_public(self, limit: int) -> list[Publication]:
        return cast(list[Publication], self._run(self._list_public(limit)))

    def listens_since(self, publication_ids: Collection[str], since: datetime) -> dict[str, list[datetime]]:
        return cast(dict[str, list[datetime]], self._run(self._listens_since(list(publication_ids), since)))

    def listen_count(self, publication_id: str) -> int:
        return cast(int, self._run(self._listen_count(publication_id)))

    @staticmethod
    def _owner_clause(listener_id: str, user_id: str | None) -> Any:
        clause = published_programmes_table.c.owner_listener_id == listener_id
        if user_id is not None:
            clause = or_(clause, published_programmes_table.c.owner_user_id == user_id)
        return clause

    @staticmethod
    def _values(publication: Publication) -> dict[str, Any]:
        values = publication.model_dump(mode="json")
        for key in ("created_at", "updated_at", "published_at", "revoked_at"):
            values[key] = getattr(publication, key)
        return values

    async def _create(self, publication: Publication) -> Publication:
        async with self.engine.begin() as connection:
            row = (
                await connection.execute(
                    insert(published_programmes_table)
                    .values(**self._values(publication))
                    .on_conflict_do_nothing(index_elements=["source_episode_id"])
                    .returning(published_programmes_table)
                )
            ).mappings().first()
        if row is None:
            raise PublicationConflictError(publication.source_episode_id)
        return _publication_from_row(row)

    async def _one(self, clause: Any) -> Publication | None:
        async with self.engine.connect() as connection:
            row = (
                await connection.execute(select(published_programmes_table).where(clause))
            ).mappings().first()
        return _publication_from_row(row) if row is not None else None

    async def _list(self, clause: Any) -> list[Publication]:
        async with self.engine.connect() as connection:
            rows = (
                await connection.execute(
                    select(published_programmes_table).where(clause)
                    .order_by(published_programmes_table.c.created_at)
                )
            ).mappings().all()
        return [_publication_from_row(row) for row in rows]

    async def _update(
        self, publication_id: str, only_from: Collection[PublicationStatus] | None, changes: dict[str, Any],
    ) -> Publication | None:
        values: dict[str, Any] = {**changes, "updated_at": utc_now()}
        for key in ("status", "visibility"):
            if key in values:
                values[key] = values[key].value
        clause = published_programmes_table.c.id == publication_id
        if only_from is not None:
            clause = and_(clause, published_programmes_table.c.status.in_([s.value for s in only_from]))
        async with self.engine.begin() as connection:
            row = (
                await connection.execute(
                    update(published_programmes_table).where(clause).values(**values)
                    .returning(published_programmes_table)
                )
            ).mappings().first()
        return _publication_from_row(row) if row is not None else None

    async def _count(self, clause: Any) -> int:
        async with self.engine.connect() as connection:
            return int((await connection.execute(
                select(func.count()).select_from(published_programmes_table).where(clause)
            )).scalar_one())

    async def _pinned_ids(self) -> set[str]:
        async with self.engine.connect() as connection:
            rows = await connection.execute(
                select(published_programmes_table.c.source_episode_id).where(
                    published_programmes_table.c.status.in_([s.value for s in PINNING_STATUSES])
                )
            )
        return {row[0] for row in rows}

    async def _pinned_bytes(self) -> int:
        async with self.engine.connect() as connection:
            return int((await connection.execute(
                select(func.coalesce(func.sum(published_programmes_table.c.bytes_total), 0)).where(
                    published_programmes_table.c.status.in_([s.value for s in PINNING_STATUSES])
                )
            )).scalar_one())

    async def _list_public(self, limit: int) -> list[Publication]:
        async with self.engine.connect() as connection:
            rows = (
                await connection.execute(
                    select(published_programmes_table)
                    .where(
                        published_programmes_table.c.status == PublicationStatus.PUBLISHED.value,
                        published_programmes_table.c.visibility == Visibility.PUBLIC.value,
                    )
                    .order_by(published_programmes_table.c.published_at.desc())
                    .limit(limit)
                )
            ).mappings().all()
        return [_publication_from_row(row) for row in rows]

    async def _listens_since(self, publication_ids: list[str], since: datetime) -> dict[str, list[datetime]]:
        if not publication_ids:
            return {}
        async with self.engine.connect() as connection:
            rows = await connection.execute(
                select(programme_listens_table.c.publication_id, programme_listens_table.c.created_at)
                .where(
                    programme_listens_table.c.publication_id.in_(publication_ids),
                    programme_listens_table.c.created_at >= since,
                )
            )
        found: dict[str, list[datetime]] = {}
        for publication_id, at in rows:
            found.setdefault(publication_id, []).append(at)
        return found

    async def _record_listen(self, publication_id: str, listener_key: str, at: datetime | None) -> bool:
        async with self.engine.begin() as connection:
            row = (
                await connection.execute(
                    insert(programme_listens_table)
                    .values(publication_id=publication_id, listener_key=listener_key, created_at=at or utc_now())
                    .on_conflict_do_nothing()
                    .returning(programme_listens_table.c.publication_id)
                )
            ).first()
        return row is not None

    async def _listen_count(self, publication_id: str) -> int:
        async with self.engine.connect() as connection:
            return int((await connection.execute(
                select(func.count()).select_from(programme_listens_table)
                .where(programme_listens_table.c.publication_id == publication_id)
            )).scalar_one())
