"""Durable reservations for dynamic-program generation limits."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, time, timedelta
from threading import RLock
from typing import Any, Protocol, cast
from uuid import uuid4

from sqlalchemy import Column, DateTime, Index, String, Table, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from wavecast.deployment import normalize_database_url
from wavecast.storage.schema import metadata

RESERVATION_TTL = timedelta(minutes=15)

quota_reservations = Table(
    "generation_quota_reservations",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("listener_id", String(128), nullable=False),
    Column("user_id", String(128), nullable=True),
    Column("program_id", String(128), nullable=True, unique=True),
    Column("status", String(16), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
)
Index("ix_generation_quota_status_expiry", quota_reservations.c.status, quota_reservations.c.expires_at)
Index("ix_generation_quota_guest", quota_reservations.c.listener_id, quota_reservations.c.status)
Index("ix_generation_quota_user_day", quota_reservations.c.user_id, quota_reservations.c.created_at, quota_reservations.c.status)
Index("ix_generation_quota_global_day", quota_reservations.c.created_at, quota_reservations.c.status)


class QuotaExceededError(RuntimeError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class GenerationQuotaRepository(Protocol):
    def reserve(
        self, listener_id: str, user_id: str | None, count: int, *,
        guest_limit: int, auth_daily_limit: int, global_daily_limit: int,
    ) -> list[str]: ...
    def charge(self, reservation_ids: list[str], program_ids: list[str]) -> None: ...
    def release(self, reservation_ids: list[str]) -> None: ...


def _period_start() -> datetime:
    return datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)


class InMemoryGenerationQuotaRepository:
    def __init__(self) -> None:
        self._rows: dict[str, dict[str, Any]] = {}
        self._lock = RLock()

    def reserve(self, listener_id: str, user_id: str | None, count: int, *, guest_limit: int, auth_daily_limit: int, global_daily_limit: int) -> list[str]:
        with self._lock:
            return self._reserve_locked(
                listener_id, user_id, count, guest_limit=guest_limit,
                auth_daily_limit=auth_daily_limit, global_daily_limit=global_daily_limit,
            )

    def _reserve_locked(self, listener_id: str, user_id: str | None, count: int, *, guest_limit: int, auth_daily_limit: int, global_daily_limit: int) -> list[str]:
        now = datetime.now(UTC)
        for row in self._rows.values():
            if row["status"] == "PENDING" and row["expires_at"] <= now:
                row["status"] = "RELEASED"
        active = [row for row in self._rows.values() if row["status"] in {"PENDING", "CHARGED"}]
        daily = [row for row in active if row["created_at"].date() == now.date()]
        if len(daily) + count > global_daily_limit:
            raise QuotaExceededError("global_daily_limit")
        if user_id is None:
            used = sum(row["listener_id"] == listener_id for row in active)
            if used + count > guest_limit:
                raise QuotaExceededError("guest_limit")
        else:
            used = sum(row["user_id"] == user_id for row in daily)
            if used + count > auth_daily_limit:
                raise QuotaExceededError("account_daily_limit")
        ids = [uuid4().hex for _ in range(count)]
        for reservation_id in ids:
            self._rows[reservation_id] = {
                "listener_id": listener_id, "user_id": user_id,
                "program_id": None, "status": "PENDING", "created_at": now,
                "expires_at": now + RESERVATION_TTL,
            }
        return ids

    def charge(self, reservation_ids: list[str], program_ids: list[str]) -> None:
        if len(reservation_ids) != len(program_ids):
            raise ValueError("reservation_count_mismatch")
        with self._lock:
            for reservation_id, program_id in zip(reservation_ids, program_ids, strict=True):
                row = self._rows[reservation_id]
                if row["status"] != "PENDING":
                    continue
                if any(other.get("program_id") == program_id for other in self._rows.values()):
                    row["status"] = "RELEASED"
                else:
                    row.update(status="CHARGED", program_id=program_id)

    def release(self, reservation_ids: list[str]) -> None:
        with self._lock:
            for reservation_id in reservation_ids:
                row = self._rows.get(reservation_id)
                if row and row["status"] == "PENDING":
                    row["status"] = "RELEASED"


class PostgresGenerationQuotaRepository:
    def __init__(self, database_url: str) -> None:
        self.engine: AsyncEngine = create_async_engine(normalize_database_url(database_url), poolclass=NullPool)
        self._run_lock = RLock()

    def reserve(self, listener_id: str, user_id: str | None, count: int, *, guest_limit: int, auth_daily_limit: int, global_daily_limit: int) -> list[str]:
        return cast(list[str], self._run(self._reserve(listener_id, user_id, count, guest_limit, auth_daily_limit, global_daily_limit)))

    def charge(self, reservation_ids: list[str], program_ids: list[str]) -> None:
        self._run(self._charge(reservation_ids, program_ids))

    def release(self, reservation_ids: list[str]) -> None:
        self._run(self._release(reservation_ids))

    def close(self) -> None:
        self._run(self.engine.dispose())

    def _run(self, coroutine: Any) -> Any:
        # Each sync call creates a fresh event loop. Keep one AsyncEngine from
        # being entered concurrently by loops running on different threads.
        with self._run_lock:
            return asyncio.run(coroutine)

    async def _reserve(self, listener_id: str, user_id: str | None, count: int, guest_limit: int, auth_daily_limit: int, global_daily_limit: int) -> list[str]:
        start = _period_start()
        now = datetime.now(UTC)
        async with self.engine.begin() as connection:
            keys = ["wavecast:quota:global:" + start.date().isoformat()]
            keys.append("wavecast:quota:listener:" + listener_id if user_id is None else "wavecast:quota:user:" + user_id + ":" + start.date().isoformat())
            for key in sorted(keys):
                await connection.execute(select(func.pg_advisory_xact_lock(func.hashtext(key))))
            await connection.execute(
                update(quota_reservations).where(
                    quota_reservations.c.status == "PENDING",
                    quota_reservations.c.expires_at <= now,
                ).values(status="RELEASED")
            )
            daily_count = await connection.scalar(
                select(func.count()).select_from(quota_reservations).where(
                    quota_reservations.c.status.in_(("PENDING", "CHARGED")),
                    quota_reservations.c.created_at >= start,
                )
            ) or 0
            if int(daily_count) + count > global_daily_limit:
                raise QuotaExceededError("global_daily_limit")
            if user_id is None:
                used = await connection.scalar(
                    select(func.count()).select_from(quota_reservations).where(
                        quota_reservations.c.listener_id == listener_id,
                        quota_reservations.c.status.in_(("PENDING", "CHARGED")),
                    )
                ) or 0
                limit = guest_limit
                reason = "guest_limit"
                actual = int(used)
            else:
                used = await connection.scalar(
                    select(func.count()).select_from(quota_reservations).where(
                        quota_reservations.c.user_id == user_id,
                        quota_reservations.c.status.in_(("PENDING", "CHARGED")),
                        quota_reservations.c.created_at >= start,
                    )
                ) or 0
                limit = auth_daily_limit
                reason = "account_daily_limit"
                actual = int(used)
            if actual + count > limit:
                raise QuotaExceededError(reason)
            ids = [uuid4().hex for _ in range(count)]
            await connection.execute(insert(quota_reservations).values([
                {"id": reservation_id, "listener_id": listener_id, "user_id": user_id,
                 "program_id": None, "status": "PENDING", "created_at": now,
                 "expires_at": now + RESERVATION_TTL}
                for reservation_id in ids
            ]))
            return ids

    async def _charge(self, reservation_ids: list[str], program_ids: list[str]) -> None:
        if len(reservation_ids) != len(program_ids):
            raise ValueError("reservation_count_mismatch")
        async with self.engine.begin() as connection:
            for program_id in sorted(set(program_ids)):
                await connection.execute(
                    select(func.pg_advisory_xact_lock(func.hashtext("wavecast:quota:program:" + program_id)))
                )
            for reservation_id, program_id in zip(reservation_ids, program_ids, strict=True):
                existing = await connection.scalar(
                    select(quota_reservations.c.id).where(
                        quota_reservations.c.program_id == program_id,
                        quota_reservations.c.status == "CHARGED",
                    )
                )
                if existing is not None:
                    await connection.execute(
                        update(quota_reservations)
                        .where(quota_reservations.c.id == reservation_id, quota_reservations.c.status == "PENDING")
                        .values(status="RELEASED")
                    )
                    continue
                result = await connection.execute(
                    update(quota_reservations)
                    .where(quota_reservations.c.id == reservation_id, quota_reservations.c.status == "PENDING")
                    .values(status="CHARGED", program_id=program_id)
                )
                if result.rowcount == 0:
                    continue

    async def _release(self, reservation_ids: list[str]) -> None:
        if not reservation_ids:
            return
        async with self.engine.begin() as connection:
            await connection.execute(
                update(quota_reservations)
                .where(quota_reservations.c.id.in_(reservation_ids), quota_reservations.c.status == "PENDING")
                .values(status="RELEASED")
            )
