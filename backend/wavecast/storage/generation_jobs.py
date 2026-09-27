"""Durable generation-job primitives for Streaming Runtime v2.

Jobs are intentionally provider-neutral. They coordinate ownership of expensive
Episode generation work without storing provider clients, prompts, responses, or
ephemeral playback URLs.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from threading import RLock
from typing import Any, Protocol, cast
from uuid import uuid4

from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, Index, Integer, String, Table, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from wavecast.deployment import normalize_database_url
from wavecast.storage.schema import metadata


class GenerationJobMode(StrEnum):
    PROGRESSIVE = "PROGRESSIVE"
    FULL = "FULL"


class GenerationJobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class GenerationJob(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    episode_id: str = Field(min_length=1, max_length=64)
    mode: GenerationJobMode
    status: GenerationJobStatus
    request_version: int = Field(ge=1)
    attempts: int = Field(ge=0)
    requested_at: datetime
    available_at: datetime
    lease_owner: str | None = Field(default=None, max_length=128)
    lease_expires_at: datetime | None = None
    last_error_code: str | None = Field(default=None, max_length=64)
    updated_at: datetime


class GenerationJobNotFoundError(KeyError):
    pass


class GenerationJobLeaseError(RuntimeError):
    pass


class GenerationJobRepository(Protocol):
    def request(
        self,
        episode_id: str,
        mode: GenerationJobMode = GenerationJobMode.PROGRESSIVE,
        *,
        available_at: datetime | None = None,
    ) -> GenerationJob: ...

    def claim(self, worker_id: str, *, lease_seconds: int = 120) -> GenerationJob | None: ...

    def complete(
        self, job_id: str, worker_id: str, request_version: int
    ) -> GenerationJob: ...

    def retry(
        self,
        job_id: str,
        worker_id: str,
        request_version: int,
        *,
        error_code: str,
        delay_seconds: int,
    ) -> GenerationJob: ...

    def cancel_for_episode(self, episode_id: str) -> GenerationJob | None: ...

    def get_for_episode(self, episode_id: str) -> GenerationJob | None: ...


generation_jobs_table = Table(
    "episode_generation_jobs",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("episode_id", String(64), nullable=False, unique=True),
    Column("mode", String(16), nullable=False),
    Column("status", String(16), nullable=False),
    Column("request_version", Integer, nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("requested_at", DateTime(timezone=True), nullable=False),
    Column("available_at", DateTime(timezone=True), nullable=False),
    Column("lease_owner", String(128), nullable=True),
    Column("lease_expires_at", DateTime(timezone=True), nullable=True),
    Column("last_error_code", String(64), nullable=True),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
Index(
    "ix_episode_generation_jobs_ready",
    generation_jobs_table.c.status,
    generation_jobs_table.c.available_at,
    generation_jobs_table.c.requested_at,
)
Index(
    "ix_episode_generation_jobs_lease",
    generation_jobs_table.c.status,
    generation_jobs_table.c.lease_expires_at,
)


def _dominant_mode(left: GenerationJobMode, right: GenerationJobMode) -> GenerationJobMode:
    if GenerationJobMode.FULL in {left, right}:
        return GenerationJobMode.FULL
    return GenerationJobMode.PROGRESSIVE


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _job_from_mapping(mapping: Any) -> GenerationJob:
    return GenerationJob.model_validate(dict(mapping))


def _validate_worker(worker_id: str) -> str:
    normalized = worker_id.strip()
    if not normalized or len(normalized) > 128:
        raise ValueError("worker_id must contain 1-128 characters")
    return normalized


def _validate_error_code(error_code: str) -> str:
    normalized = error_code.strip()
    if not normalized or len(normalized) > 64:
        raise ValueError("error_code must contain 1-64 characters")
    return normalized


class InMemoryGenerationJobRepository:
    def __init__(self, *, now: Callable[[], datetime] = _utc_now) -> None:
        self._jobs_by_episode: dict[str, GenerationJob] = {}
        self._jobs_by_id: dict[str, GenerationJob] = {}
        self._lock = RLock()
        self._now = now

    def request(
        self,
        episode_id: str,
        mode: GenerationJobMode = GenerationJobMode.PROGRESSIVE,
        *,
        available_at: datetime | None = None,
    ) -> GenerationJob:
        with self._lock:
            now = self._now()
            ready_at = available_at or now
            existing = self._jobs_by_episode.get(episode_id)
            if existing is None:
                job = GenerationJob(
                    id=uuid4().hex,
                    episode_id=episode_id,
                    mode=mode,
                    status=GenerationJobStatus.PENDING,
                    request_version=1,
                    attempts=0,
                    requested_at=now,
                    available_at=ready_at,
                    updated_at=now,
                )
            else:
                update_values: dict[str, Any] = {
                    "mode": _dominant_mode(existing.mode, mode),
                    "request_version": existing.request_version + 1,
                    "requested_at": now,
                    "updated_at": now,
                    "last_error_code": None,
                }
                if existing.status in {
                    GenerationJobStatus.COMPLETED,
                    GenerationJobStatus.CANCELLED,
                }:
                    update_values.update(
                        status=GenerationJobStatus.PENDING,
                        attempts=0,
                        available_at=ready_at,
                        lease_owner=None,
                        lease_expires_at=None,
                    )
                elif existing.status is GenerationJobStatus.PENDING:
                    update_values["available_at"] = min(existing.available_at, ready_at)
                job = existing.model_copy(update=update_values)
            self._jobs_by_episode[episode_id] = job
            self._jobs_by_id[job.id] = job
            return job.model_copy(deep=True)

    def claim(self, worker_id: str, *, lease_seconds: int = 120) -> GenerationJob | None:
        worker_id = _validate_worker(worker_id)
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        with self._lock:
            now = self._now()
            self._requeue_expired(now)
            candidates = sorted(
                (
                    job
                    for job in self._jobs_by_episode.values()
                    if job.status is GenerationJobStatus.PENDING
                    and job.available_at <= now
                ),
                key=lambda item: (item.requested_at, item.id),
            )
            if not candidates:
                return None
            current = candidates[0]
            claimed = current.model_copy(
                update={
                    "status": GenerationJobStatus.RUNNING,
                    "lease_owner": worker_id,
                    "lease_expires_at": now + timedelta(seconds=lease_seconds),
                    "attempts": current.attempts + 1,
                    "updated_at": now,
                }
            )
            self._store(claimed)
            return claimed.model_copy(deep=True)

    def complete(
        self, job_id: str, worker_id: str, request_version: int
    ) -> GenerationJob:
        worker_id = _validate_worker(worker_id)
        with self._lock:
            current = self._running_owned(job_id, worker_id)
            now = self._now()
            if current.request_version != request_version:
                updated = current.model_copy(
                    update={
                        "status": GenerationJobStatus.PENDING,
                        "available_at": now,
                        "lease_owner": None,
                        "lease_expires_at": None,
                        "last_error_code": None,
                        "updated_at": now,
                    }
                )
            else:
                updated = current.model_copy(
                    update={
                        "status": GenerationJobStatus.COMPLETED,
                        "lease_owner": None,
                        "lease_expires_at": None,
                        "last_error_code": None,
                        "updated_at": now,
                    }
                )
            self._store(updated)
            return updated.model_copy(deep=True)

    def retry(
        self,
        job_id: str,
        worker_id: str,
        request_version: int,
        *,
        error_code: str,
        delay_seconds: int,
    ) -> GenerationJob:
        worker_id = _validate_worker(worker_id)
        error_code = _validate_error_code(error_code)
        if delay_seconds < 0:
            raise ValueError("delay_seconds must be non-negative")
        with self._lock:
            current = self._running_owned(job_id, worker_id)
            now = self._now()
            superseded = current.request_version != request_version
            updated = current.model_copy(
                update={
                    "status": GenerationJobStatus.PENDING,
                    "available_at": now if superseded else now + timedelta(seconds=delay_seconds),
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "last_error_code": None if superseded else error_code,
                    "updated_at": now,
                }
            )
            self._store(updated)
            return updated.model_copy(deep=True)

    def cancel_for_episode(self, episode_id: str) -> GenerationJob | None:
        with self._lock:
            current = self._jobs_by_episode.get(episode_id)
            if current is None:
                return None
            now = self._now()
            updated = current.model_copy(
                update={
                    "status": GenerationJobStatus.CANCELLED,
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "updated_at": now,
                }
            )
            self._store(updated)
            return updated.model_copy(deep=True)

    def get_for_episode(self, episode_id: str) -> GenerationJob | None:
        with self._lock:
            current = self._jobs_by_episode.get(episode_id)
            return current.model_copy(deep=True) if current is not None else None

    def _requeue_expired(self, now: datetime) -> None:
        for current in list(self._jobs_by_episode.values()):
            if (
                current.status is GenerationJobStatus.RUNNING
                and current.lease_expires_at is not None
                and current.lease_expires_at <= now
            ):
                self._store(
                    current.model_copy(
                        update={
                            "status": GenerationJobStatus.PENDING,
                            "available_at": now,
                            "lease_owner": None,
                            "lease_expires_at": None,
                            "updated_at": now,
                        }
                    )
                )

    def _running_owned(self, job_id: str, worker_id: str) -> GenerationJob:
        current = self._jobs_by_id.get(job_id)
        if current is None:
            raise GenerationJobNotFoundError(job_id)
        if (
            current.status is not GenerationJobStatus.RUNNING
            or current.lease_owner != worker_id
        ):
            raise GenerationJobLeaseError("generation job lease is not owned by worker")
        return current

    def _store(self, job: GenerationJob) -> None:
        self._jobs_by_episode[job.episode_id] = job
        self._jobs_by_id[job.id] = job


class PostgresGenerationJobRepository:
    def __init__(self, database_url: str) -> None:
        self.engine: AsyncEngine = create_async_engine(
            normalize_database_url(database_url), poolclass=NullPool
        )
        self._run_lock = RLock()

    def request(
        self,
        episode_id: str,
        mode: GenerationJobMode = GenerationJobMode.PROGRESSIVE,
        *,
        available_at: datetime | None = None,
    ) -> GenerationJob:
        return cast(
            GenerationJob,
            self._run(self._request(episode_id, mode, available_at=available_at)),
        )

    def claim(self, worker_id: str, *, lease_seconds: int = 120) -> GenerationJob | None:
        worker_id = _validate_worker(worker_id)
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        return cast(
            GenerationJob | None,
            self._run(self._claim(worker_id, lease_seconds=lease_seconds)),
        )

    def complete(
        self, job_id: str, worker_id: str, request_version: int
    ) -> GenerationJob:
        worker_id = _validate_worker(worker_id)
        return cast(
            GenerationJob,
            self._run(self._complete(job_id, worker_id, request_version)),
        )

    def retry(
        self,
        job_id: str,
        worker_id: str,
        request_version: int,
        *,
        error_code: str,
        delay_seconds: int,
    ) -> GenerationJob:
        worker_id = _validate_worker(worker_id)
        error_code = _validate_error_code(error_code)
        if delay_seconds < 0:
            raise ValueError("delay_seconds must be non-negative")
        return cast(
            GenerationJob,
            self._run(
                self._retry(
                    job_id,
                    worker_id,
                    request_version,
                    error_code=error_code,
                    delay_seconds=delay_seconds,
                )
            ),
        )

    def cancel_for_episode(self, episode_id: str) -> GenerationJob | None:
        return cast(
            GenerationJob | None,
            self._run(self._cancel_for_episode(episode_id)),
        )

    def get_for_episode(self, episode_id: str) -> GenerationJob | None:
        return cast(
            GenerationJob | None,
            self._run(self._get_for_episode(episode_id)),
        )

    def close(self) -> None:
        self._run(self.engine.dispose())

    def _run(self, coroutine: Any) -> Any:
        with self._run_lock:
            return asyncio.run(coroutine)

    async def _request(
        self,
        episode_id: str,
        mode: GenerationJobMode,
        *,
        available_at: datetime | None,
    ) -> GenerationJob:
        now = _utc_now()
        ready_at = available_at or now
        async with self.engine.begin() as connection:
            await connection.execute(
                select(
                    func.pg_advisory_xact_lock(
                        func.hashtext("wavecast:generation-job:" + episode_id)
                    )
                )
            )
            row = (
                await connection.execute(
                    select(generation_jobs_table)
                    .where(generation_jobs_table.c.episode_id == episode_id)
                    .with_for_update()
                )
            ).mappings().first()
            if row is None:
                values = {
                    "id": uuid4().hex,
                    "episode_id": episode_id,
                    "mode": mode.value,
                    "status": GenerationJobStatus.PENDING.value,
                    "request_version": 1,
                    "attempts": 0,
                    "requested_at": now,
                    "available_at": ready_at,
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "last_error_code": None,
                    "updated_at": now,
                }
                row = (
                    await connection.execute(
                        insert(generation_jobs_table).values(**values).returning(
                            generation_jobs_table
                        )
                    )
                ).mappings().one()
                return _job_from_mapping(row)

            current = _job_from_mapping(row)
            values: dict[str, Any] = {
                "mode": _dominant_mode(current.mode, mode).value,
                "request_version": current.request_version + 1,
                "requested_at": now,
                "updated_at": now,
                "last_error_code": None,
            }
            if current.status in {
                GenerationJobStatus.COMPLETED,
                GenerationJobStatus.CANCELLED,
            }:
                values.update(
                    status=GenerationJobStatus.PENDING.value,
                    attempts=0,
                    available_at=ready_at,
                    lease_owner=None,
                    lease_expires_at=None,
                )
            elif current.status is GenerationJobStatus.PENDING:
                values["available_at"] = min(current.available_at, ready_at)
            row = (
                await connection.execute(
                    update(generation_jobs_table)
                    .where(generation_jobs_table.c.id == current.id)
                    .values(**values)
                    .returning(generation_jobs_table)
                )
            ).mappings().one()
            return _job_from_mapping(row)

    async def _claim(
        self, worker_id: str, *, lease_seconds: int
    ) -> GenerationJob | None:
        now = _utc_now()
        async with self.engine.begin() as connection:
            await connection.execute(
                update(generation_jobs_table)
                .where(
                    generation_jobs_table.c.status == GenerationJobStatus.RUNNING.value,
                    generation_jobs_table.c.lease_expires_at.is_not(None),
                    generation_jobs_table.c.lease_expires_at <= now,
                )
                .values(
                    status=GenerationJobStatus.PENDING.value,
                    available_at=now,
                    lease_owner=None,
                    lease_expires_at=None,
                    updated_at=now,
                )
            )
            row = (
                await connection.execute(
                    select(generation_jobs_table)
                    .where(
                        generation_jobs_table.c.status
                        == GenerationJobStatus.PENDING.value,
                        generation_jobs_table.c.available_at <= now,
                    )
                    .order_by(
                        generation_jobs_table.c.requested_at,
                        generation_jobs_table.c.id,
                    )
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
            ).mappings().first()
            if row is None:
                return None
            current = _job_from_mapping(row)
            claimed = (
                await connection.execute(
                    update(generation_jobs_table)
                    .where(generation_jobs_table.c.id == current.id)
                    .values(
                        status=GenerationJobStatus.RUNNING.value,
                        lease_owner=worker_id,
                        lease_expires_at=now + timedelta(seconds=lease_seconds),
                        attempts=current.attempts + 1,
                        updated_at=now,
                    )
                    .returning(generation_jobs_table)
                )
            ).mappings().one()
            return _job_from_mapping(claimed)

    async def _complete(
        self, job_id: str, worker_id: str, request_version: int
    ) -> GenerationJob:
        now = _utc_now()
        async with self.engine.begin() as connection:
            current = await self._locked_owned(connection, job_id, worker_id)
            if current.request_version != request_version:
                values = {
                    "status": GenerationJobStatus.PENDING.value,
                    "available_at": now,
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "last_error_code": None,
                    "updated_at": now,
                }
            else:
                values = {
                    "status": GenerationJobStatus.COMPLETED.value,
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "last_error_code": None,
                    "updated_at": now,
                }
            row = (
                await connection.execute(
                    update(generation_jobs_table)
                    .where(generation_jobs_table.c.id == job_id)
                    .values(**values)
                    .returning(generation_jobs_table)
                )
            ).mappings().one()
            return _job_from_mapping(row)

    async def _retry(
        self,
        job_id: str,
        worker_id: str,
        request_version: int,
        *,
        error_code: str,
        delay_seconds: int,
    ) -> GenerationJob:
        now = _utc_now()
        async with self.engine.begin() as connection:
            current = await self._locked_owned(connection, job_id, worker_id)
            superseded = current.request_version != request_version
            row = (
                await connection.execute(
                    update(generation_jobs_table)
                    .where(generation_jobs_table.c.id == job_id)
                    .values(
                        status=GenerationJobStatus.PENDING.value,
                        available_at=(
                            now
                            if superseded
                            else now + timedelta(seconds=delay_seconds)
                        ),
                        lease_owner=None,
                        lease_expires_at=None,
                        last_error_code=None if superseded else error_code,
                        updated_at=now,
                    )
                    .returning(generation_jobs_table)
                )
            ).mappings().one()
            return _job_from_mapping(row)

    async def _cancel_for_episode(self, episode_id: str) -> GenerationJob | None:
        now = _utc_now()
        async with self.engine.begin() as connection:
            row = (
                await connection.execute(
                    update(generation_jobs_table)
                    .where(generation_jobs_table.c.episode_id == episode_id)
                    .values(
                        status=GenerationJobStatus.CANCELLED.value,
                        lease_owner=None,
                        lease_expires_at=None,
                        updated_at=now,
                    )
                    .returning(generation_jobs_table)
                )
            ).mappings().first()
        return _job_from_mapping(row) if row is not None else None

    async def _get_for_episode(self, episode_id: str) -> GenerationJob | None:
        async with self.engine.connect() as connection:
            row = (
                await connection.execute(
                    select(generation_jobs_table).where(
                        generation_jobs_table.c.episode_id == episode_id
                    )
                )
            ).mappings().first()
        return _job_from_mapping(row) if row is not None else None

    async def _locked_owned(
        self, connection: Any, job_id: str, worker_id: str
    ) -> GenerationJob:
        row = (
            await connection.execute(
                select(generation_jobs_table)
                .where(generation_jobs_table.c.id == job_id)
                .with_for_update()
            )
        ).mappings().first()
        if row is None:
            raise GenerationJobNotFoundError(job_id)
        current = _job_from_mapping(row)
        if (
            current.status is not GenerationJobStatus.RUNNING
            or current.lease_owner != worker_id
        ):
            raise GenerationJobLeaseError("generation job lease is not owned by worker")
        return current
