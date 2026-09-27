from __future__ import annotations

from datetime import UTC, datetime, timedelta

from wavecast.storage.generation_jobs import (
    GenerationJobMode,
    GenerationJobStatus,
    InMemoryGenerationJobRepository,
)


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 9, 27, 8, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


def test_requests_coalesce_per_episode_and_full_mode_dominates() -> None:
    clock = Clock()
    repository = InMemoryGenerationJobRepository(now=clock.now)

    first = repository.request("episode-1")
    clock.advance(1)
    second = repository.request("episode-1", GenerationJobMode.FULL)

    assert second.id == first.id
    assert second.mode is GenerationJobMode.FULL
    assert second.status is GenerationJobStatus.PENDING
    assert second.request_version == first.request_version + 1


def test_same_mode_active_request_is_idempotent() -> None:
    clock = Clock()
    repository = InMemoryGenerationJobRepository(now=clock.now)

    first = repository.request("episode-1")
    second = repository.request("episode-1")
    claimed = repository.claim("worker-a", lease_seconds=60)

    assert second == first
    assert claimed is not None

    repeated = repository.request("episode-1")

    assert repeated.id == claimed.id
    assert repeated.status is GenerationJobStatus.RUNNING
    assert repeated.request_version == claimed.request_version
    assert repeated.lease_owner == "worker-a"


def test_new_request_while_running_cannot_be_consumed_by_old_completion() -> None:
    clock = Clock()
    repository = InMemoryGenerationJobRepository(now=clock.now)
    requested = repository.request("episode-1")
    claimed = repository.claim("worker-a", lease_seconds=60)

    assert claimed is not None
    assert claimed.id == requested.id
    assert claimed.status is GenerationJobStatus.RUNNING

    clock.advance(1)
    newer = repository.request("episode-1", GenerationJobMode.FULL)
    assert newer.status is GenerationJobStatus.RUNNING
    assert newer.request_version == claimed.request_version + 1

    completed = repository.complete(
        claimed.id,
        "worker-a",
        claimed.request_version,
    )

    assert completed.status is GenerationJobStatus.PENDING
    assert completed.mode is GenerationJobMode.FULL
    assert completed.request_version == newer.request_version
    assert completed.lease_owner is None


def test_expired_lease_is_reclaimed_by_another_worker() -> None:
    clock = Clock()
    repository = InMemoryGenerationJobRepository(now=clock.now)
    repository.request("episode-1")
    first = repository.claim("worker-a", lease_seconds=10)

    assert first is not None
    clock.advance(11)

    second = repository.claim("worker-b", lease_seconds=10)

    assert second is not None
    assert second.id == first.id
    assert second.lease_owner == "worker-b"
    assert second.attempts == 2


def test_renewed_lease_prevents_duplicate_claim() -> None:
    clock = Clock()
    repository = InMemoryGenerationJobRepository(now=clock.now)
    repository.request("episode-1")
    claimed = repository.claim("worker-a", lease_seconds=10)

    assert claimed is not None
    clock.advance(8)
    renewed = repository.renew_lease(claimed.id, "worker-a", lease_seconds=10)

    assert renewed.lease_expires_at == clock.now() + timedelta(seconds=10)

    clock.advance(3)
    assert repository.claim("worker-b", lease_seconds=10) is None


def test_retry_delays_same_request_and_records_only_safe_error_code() -> None:
    clock = Clock()
    repository = InMemoryGenerationJobRepository(now=clock.now)
    repository.request("episode-1")
    claimed = repository.claim("worker-a")

    assert claimed is not None
    retried = repository.retry(
        claimed.id,
        "worker-a",
        claimed.request_version,
        error_code="provider_timeout",
        delay_seconds=30,
    )

    assert retried.status is GenerationJobStatus.PENDING
    assert retried.last_error_code == "provider_timeout"
    assert repository.claim("worker-b") is None

    clock.advance(30)
    reclaimed = repository.claim("worker-b")
    assert reclaimed is not None
    assert reclaimed.id == claimed.id


def test_failed_job_is_terminal_but_new_request_reactivates_it() -> None:
    clock = Clock()
    repository = InMemoryGenerationJobRepository(now=clock.now)
    original = repository.request("episode-1")
    claimed = repository.claim("worker-a")

    assert claimed is not None
    failed = repository.fail(
        claimed.id,
        "worker-a",
        claimed.request_version,
        error_code="invalid_generation_contract",
    )

    assert failed.status is GenerationJobStatus.FAILED
    assert failed.last_error_code == "invalid_generation_contract"
    assert repository.claim("worker-b") is None

    clock.advance(1)
    reactivated = repository.request("episode-1")

    assert reactivated.id == original.id
    assert reactivated.status is GenerationJobStatus.PENDING
    assert reactivated.last_error_code is None
    assert reactivated.attempts == 0
    assert reactivated.request_version == original.request_version + 1


def test_cancelled_job_can_be_reactivated_by_new_request() -> None:
    clock = Clock()
    repository = InMemoryGenerationJobRepository(now=clock.now)
    original = repository.request("episode-1")
    cancelled = repository.cancel_for_episode("episode-1")

    assert cancelled is not None
    assert cancelled.status is GenerationJobStatus.CANCELLED

    clock.advance(1)
    reactivated = repository.request("episode-1")

    assert reactivated.id == original.id
    assert reactivated.status is GenerationJobStatus.PENDING
    assert reactivated.attempts == 0
    assert reactivated.request_version == original.request_version + 1
