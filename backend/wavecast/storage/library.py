"""Durable per-account library rows and idempotent guest-state merge."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
from threading import RLock
from typing import Any, Protocol, cast

from sqlalchemy import Column, DateTime, Index, String, Table, delete, func, select
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from wavecast.deployment import normalize_database_url
from wavecast.storage.schema import metadata

LIBRARY_KINDS = ("FAVORITE", "RECENT", "SAVED", "CREATED")
MAX_RECENTS = 20

user_library_entries = Table(
    "user_library_entries",
    metadata,
    Column("user_id", String(128), primary_key=True),
    Column("kind", String(16), primary_key=True),
    Column("resource_id", String(128), primary_key=True),
    Column("payload", JSONB, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
Index("ix_user_library_user_kind_updated", user_library_entries.c.user_id, user_library_entries.c.kind, user_library_entries.c.updated_at)


def empty_library() -> dict[str, Any]:
    return {
        "version": 1,
        "favoriteSeedIds": [],
        "recentPrograms": [],
        "savedEpisodes": [],
        "createdProgramIds": [],
    }


def _timestamp(payload: Mapping[str, Any], key: str) -> float:
    value = payload.get(key)
    return float(value) if isinstance(value, (int, float)) else 0.0


def _merge_row(
    rows: dict[tuple[str, str], dict[str, Any]],
    kind: str,
    resource_id: str,
    payload: dict[str, Any],
) -> None:
    key = (kind, resource_id)
    current = rows.get(key)
    date_field = "savedAt" if kind == "SAVED" else "updatedAt"
    if current is None or _timestamp(payload, date_field) >= _timestamp(current, date_field):
        rows[key] = payload


def _library_rows(value: Mapping[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for kind, list_key, id_key in (
        ("FAVORITE", "favoriteSeedIds", None),
        ("CREATED", "createdProgramIds", None),
        ("RECENT", "recentPrograms", "episodeId"),
        ("SAVED", "savedEpisodes", "episodeId"),
    ):
        items = value.get(list_key, [])
        if not isinstance(items, list):
            continue
        for item in items:
            if id_key is None and isinstance(item, str) and item:
                _merge_row(rows, kind, item, {"id": item})
            elif id_key is not None and isinstance(item, dict):
                resource_id = item.get(id_key)
                if isinstance(resource_id, str) and resource_id:
                    _merge_row(rows, kind, resource_id, dict(item))
    return rows


def _snapshot(rows: Mapping[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    favorites = sorted(resource_id for (kind, resource_id) in rows if kind == "FAVORITE")
    created = sorted(resource_id for (kind, resource_id) in rows if kind == "CREATED")
    recents = [payload for (kind, _), payload in rows.items() if kind == "RECENT"]
    saved = [payload for (kind, _), payload in rows.items() if kind == "SAVED"]
    recents.sort(key=lambda item: _timestamp(item, "updatedAt"), reverse=True)
    saved.sort(key=lambda item: _timestamp(item, "savedAt"), reverse=True)
    return {
        "version": 1,
        "favoriteSeedIds": favorites,
        "recentPrograms": recents[:MAX_RECENTS],
        "savedEpisodes": saved,
        "createdProgramIds": created,
    }


class UserLibraryRepository(Protocol):
    def snapshot(self, user_id: str) -> dict[str, Any]: ...
    def merge(self, user_id: str, library: Mapping[str, Any]) -> dict[str, Any]: ...
    def put(self, user_id: str, kind: str, resource_id: str, payload: Mapping[str, Any]) -> dict[str, Any]: ...
    def delete(self, user_id: str, kind: str, resource_id: str) -> dict[str, Any]: ...


class InMemoryUserLibraryRepository:
    def __init__(self) -> None:
        self._rows: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
        self._lock = RLock()

    def snapshot(self, user_id: str) -> dict[str, Any]:
        with self._lock:
            return _snapshot(self._rows.get(user_id, {}))

    def merge(self, user_id: str, library: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            rows = self._rows.setdefault(user_id, {})
            for (kind, resource_id), payload in _library_rows(library).items():
                _merge_row(rows, kind, resource_id, payload)
            return _snapshot(rows)

    def put(self, user_id: str, kind: str, resource_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        if kind not in LIBRARY_KINDS:
            raise ValueError("invalid_library_kind")
        with self._lock:
            rows = self._rows.setdefault(user_id, {})
            _merge_row(rows, kind, resource_id, dict(payload))
            return _snapshot(rows)

    def delete(self, user_id: str, kind: str, resource_id: str) -> dict[str, Any]:
        with self._lock:
            self._rows.setdefault(user_id, {}).pop((kind, resource_id), None)
            return _snapshot(self._rows[user_id])


class PostgresUserLibraryRepository:
    def __init__(self, database_url: str) -> None:
        self.engine: AsyncEngine = create_async_engine(normalize_database_url(database_url), poolclass=NullPool)

    def snapshot(self, user_id: str) -> dict[str, Any]:
        return cast(dict[str, Any], self._run(self._snapshot(user_id)))

    def merge(self, user_id: str, library: Mapping[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], self._run(self._merge(user_id, dict(library))))

    def put(self, user_id: str, kind: str, resource_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        if kind not in LIBRARY_KINDS:
            raise ValueError("invalid_library_kind")
        return cast(dict[str, Any], self._run(self._put(user_id, kind, resource_id, dict(payload))))

    def delete(self, user_id: str, kind: str, resource_id: str) -> dict[str, Any]:
        return cast(dict[str, Any], self._run(self._delete(user_id, kind, resource_id)))

    def close(self) -> None:
        self._run(self.engine.dispose())

    @staticmethod
    def _run(coroutine: Any) -> Any:
        return asyncio.run(coroutine)

    async def _rows(self, user_id: str, connection: Any) -> dict[tuple[str, str], dict[str, Any]]:
        result = await connection.execute(
            select(user_library_entries.c.kind, user_library_entries.c.resource_id, user_library_entries.c.payload)
            .where(user_library_entries.c.user_id == user_id)
        )
        return {(row.kind, row.resource_id): dict(row.payload) for row in result}

    async def _snapshot(self, user_id: str) -> dict[str, Any]:
        async with self.engine.connect() as connection:
            rows = await self._rows(user_id, connection)
        return _snapshot(rows)

    async def _upsert(self, user_id: str, rows: Mapping[tuple[str, str], dict[str, Any]], connection: Any) -> None:
        if not rows:
            return
        now = datetime.now(UTC)
        values = [
            {"user_id": user_id, "kind": kind, "resource_id": resource_id, "payload": payload, "updated_at": now}
            for (kind, resource_id), payload in rows.items()
        ]
        statement = insert(user_library_entries).values(values)
        statement = statement.on_conflict_do_update(
            index_elements=[
                user_library_entries.c.user_id,
                user_library_entries.c.kind,
                user_library_entries.c.resource_id,
            ],
            set_={"payload": statement.excluded.payload, "updated_at": now},
        )
        await connection.execute(statement)

    async def _lock_user(self, user_id: str, connection: Any) -> None:
        await connection.execute(
            select(func.pg_advisory_xact_lock(func.hashtext("wavecast:library:" + user_id)))
        )

    async def _merge(self, user_id: str, library: dict[str, Any]) -> dict[str, Any]:
        async with self.engine.begin() as connection:
            await self._lock_user(user_id, connection)
            rows = await self._rows(user_id, connection)
            for key, payload in _library_rows(library).items():
                _merge_row(rows, key[0], key[1], payload)
            recent_keys = sorted(
                (key for key in rows if key[0] == "RECENT"),
                key=lambda key: _timestamp(rows[key], "updatedAt"),
                reverse=True,
            )
            for key in recent_keys[MAX_RECENTS:]:
                del rows[key]
            await self._upsert(user_id, rows, connection)
            if recent_keys[MAX_RECENTS:]:
                await connection.execute(
                    delete(user_library_entries).where(
                        user_library_entries.c.user_id == user_id,
                        user_library_entries.c.kind == "RECENT",
                        user_library_entries.c.resource_id.in_([key[1] for key in recent_keys[MAX_RECENTS:]]),
                    )
                )
        return _snapshot(rows)

    async def _put(self, user_id: str, kind: str, resource_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with self.engine.begin() as connection:
            await self._lock_user(user_id, connection)
            rows = await self._rows(user_id, connection)
            key = (kind, resource_id)
            previous = rows.get(key)
            _merge_row(rows, kind, resource_id, payload)
            if rows[key] != previous:
                await self._upsert(user_id, {key: rows[key]}, connection)
            if kind == "RECENT":
                rows = await self._rows(user_id, connection)
                recent = sorted(
                    (key for key in rows if key[0] == "RECENT"),
                    key=lambda key: _timestamp(rows[key], "updatedAt"),
                    reverse=True,
                )
                if len(recent) > MAX_RECENTS:
                    await connection.execute(
                        delete(user_library_entries).where(
                            user_library_entries.c.user_id == user_id,
                            user_library_entries.c.kind == "RECENT",
                            user_library_entries.c.resource_id.in_([key[1] for key in recent[MAX_RECENTS:]]),
                        )
                    )
            rows = await self._rows(user_id, connection)
        return _snapshot(rows)

    async def _delete(self, user_id: str, kind: str, resource_id: str) -> dict[str, Any]:
        async with self.engine.begin() as connection:
            await self._lock_user(user_id, connection)
            await connection.execute(
                delete(user_library_entries).where(
                    user_library_entries.c.user_id == user_id,
                    user_library_entries.c.kind == kind,
                    user_library_entries.c.resource_id == resource_id,
                )
            )
            rows = await self._rows(user_id, connection)
        return _snapshot(rows)
