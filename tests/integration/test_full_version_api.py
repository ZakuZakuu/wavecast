import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from wavecast.full_version import (
    FULL_VERSION_TIMEOUT_SECONDS,
    MAX_CONCURRENT_FULL_VERSIONS,
    FullVersionStatus,
    full_version_status,
)
from wavecast.orchestration.worker import GenerationWorker
from wavecast.proposals import InMemoryProgramProposalRepository
from wavecast.storage.generation_jobs import (
    GenerationJob,
    GenerationJobMode,
    GenerationJobStatus,
    InMemoryGenerationJobRepository,
)

import services.api.main as api_module


@pytest.fixture
def jobs(monkeypatch: pytest.MonkeyPatch) -> InMemoryGenerationJobRepository:
    repository = InMemoryGenerationJobRepository()
    monkeypatch.setattr(api_module, "generation_job_repository", repository)
    monkeypatch.setattr(
        api_module, "generation_worker",
        GenerationWorker(repository, api_module.orchestrator, worker_id="full-version-test"),
    )
    monkeypatch.setattr(api_module, "proposal_repository", InMemoryProgramProposalRepository())
    return repository


def _headers() -> dict[str, str]:
    return {"X-Wavecast-Listener": f"full-version-{uuid4().hex}"}


def _prepare(client: TestClient, headers: dict[str, str], topic: str | None = None):
    return client.post(
        "/api/full-versions",
        json={"prompt": topic or f"完整版测试 {uuid4().hex}", "duration_intent": "SHORT", "count": 1},
        headers=headers,
    )


def _status(client: TestClient, headers: dict[str, str], *episode_ids: str) -> list[dict]:
    response = client.get("/api/full-versions", params={"episode_ids": ",".join(episode_ids)}, headers=headers)
    assert response.status_code == 200
    return response.json()


def test_status_follows_the_job_and_gives_up_on_a_stalled_one() -> None:
    now = datetime.now(UTC)
    job = GenerationJob(
        id="j", episode_id="e", mode=GenerationJobMode.FULL, status=GenerationJobStatus.RUNNING,
        request_version=1, attempts=1, requested_at=now, available_at=now, updated_at=now,
    )
    episode = api_module.orchestrator.start_or_resume(
        api_module._static_seed(api_module.SEEDS[0].id), "unit-listener", None,
    )
    assert full_version_status(episode, None, now) is FullVersionStatus.NONE
    assert full_version_status(episode, job, now) is FullVersionStatus.PREPARING
    stalled = job.model_copy(update={"requested_at": now - timedelta(seconds=FULL_VERSION_TIMEOUT_SECONDS + 1)})
    assert full_version_status(episode, stalled, now) is FullVersionStatus.FAILED
    failed = job.model_copy(update={"status": GenerationJobStatus.FAILED})
    assert full_version_status(episode, failed, now) is FullVersionStatus.FAILED
    cancelled = job.model_copy(update={"status": GenerationJobStatus.CANCELLED})
    assert full_version_status(episode, cancelled, now) is FullVersionStatus.NONE


def test_prepare_only_makes_the_episode_and_reports_it_preparing_then_ready(
    jobs: InMemoryGenerationJobRepository,
) -> None:
    client = TestClient(api_module.app)
    headers = _headers()
    response = _prepare(client, headers)
    assert response.status_code == 202
    episode = response.json()
    assert episode["is_listener_active"] is False
    assert episode["state"] == "MATERIALIZING"
    queued = jobs.get_for_episode(episode["id"])
    assert queued is not None and queued.mode is GenerationJobMode.FULL

    [item] = _status(client, headers, episode["id"])
    assert item["status"] == "preparing"
    assert item["programme_id"] == episode["seed_id"]

    assert asyncio.run(api_module.generation_worker.run_once()) is True
    [item] = _status(client, headers, episode["id"])
    assert (item["status"], item["progress"]) == ("ready", 100)


def test_only_two_can_be_prepared_at_once_and_a_refusal_costs_no_allowance(
    jobs: InMemoryGenerationJobRepository,
) -> None:
    client = TestClient(api_module.app)
    headers = _headers()
    first = _prepare(client, headers).json()
    second = _prepare(client, headers).json()
    assert MAX_CONCURRENT_FULL_VERSIONS == 2
    refused = _prepare(client, headers)
    assert refused.status_code == 429
    assert "最多同时准备 2 档" in refused.json()["detail"]
    # The same episode asked for again is not a third one.
    assert client.post(f"/api/episodes/{first['id']}/materialize", headers=headers).status_code == 202
    # Someone else is not held up by this listener's two.
    assert _prepare(client, _headers()).status_code == 202

    assert asyncio.run(api_module.generation_worker.run_once()) is True
    # One finished: a slot is free again.
    assert _prepare(client, headers).status_code == 202
    assert {item["episode_id"] for item in _status(client, headers, first["id"], second["id"])} == {first["id"], second["id"]}


def test_status_is_only_given_to_the_owner(jobs: InMemoryGenerationJobRepository) -> None:
    client = TestClient(api_module.app)
    owner = _headers()
    episode = _prepare(client, owner).json()
    assert _status(client, _headers(), episode["id"], "no-such-episode") == []
    assert len(_status(client, owner, episode["id"], "no-such-episode")) == 1


def test_a_preparation_stalled_for_twenty_minutes_is_failed_frees_its_slot_and_can_be_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    age = [timedelta(minutes=21)]
    stale_jobs = InMemoryGenerationJobRepository(now=lambda: datetime.now(UTC) - age[0])
    monkeypatch.setattr(api_module, "generation_job_repository", stale_jobs)
    monkeypatch.setattr(api_module, "proposal_repository", InMemoryProgramProposalRepository())
    client = TestClient(api_module.app)
    headers = _headers()
    stalled = [_prepare(client, headers).json() for _ in range(2)]
    assert {item["status"] for item in _status(client, headers, *[e["id"] for e in stalled])} == {"failed"}

    # Neither counts against the limit any more, so a new one can start.
    assert _prepare(client, headers).status_code == 202

    # Retrying a stalled one starts it over with a fresh clock.
    age[0] = timedelta(0)
    retried = client.post(f"/api/episodes/{stalled[0]['id']}/materialize", headers=headers)
    assert retried.status_code == 202
    [item] = _status(client, headers, stalled[0]["id"])
    assert item["status"] == "preparing"
