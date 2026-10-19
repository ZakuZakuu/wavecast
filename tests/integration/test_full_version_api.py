import asyncio
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
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


def _made(client: TestClient, headers: dict[str, str], accepted) -> dict:
    """Waits for the background work of an accepted request, and gives how it ended."""
    assert accepted.status_code == 202
    request_id = accepted.json()["request_id"]
    for _ in range(200):
        [item] = client.get("/api/full-versions/requests", params={"ids": request_id}, headers=headers).json()
        if item["status"] != "creating":
            return item
        time.sleep(0.05)
    raise AssertionError("the request never finished")


def _prepared(client: TestClient, headers: dict[str, str], topic: str | None = None) -> dict:
    item = _made(client, headers, _prepare(client, headers, topic))
    assert item["status"] == "ready", item
    return {"id": item["episode_id"], "seed_id": item["programme_id"]}


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
    with TestClient(api_module.app) as client:
        _prepare_only_flow(client, jobs)


def _prepare_only_flow(client: TestClient, jobs: InMemoryGenerationJobRepository) -> None:
    headers = _headers()
    accepted = _prepare(client, headers)
    # It answers before the programme exists: the listener is free to go.
    assert accepted.status_code == 202 and set(accepted.json()) == {"request_id"}
    item = _made(client, headers, accepted)
    assert item["status"] == "ready"
    episode = client.get(f"/api/episodes/{item['episode_id']}", headers=headers).json()
    assert episode["is_listener_active"] is False
    assert episode["state"] == "MATERIALIZING"
    queued = jobs.get_for_episode(episode["id"])
    assert queued is not None and queued.mode is GenerationJobMode.FULL

    [status] = _status(client, headers, episode["id"])
    assert status["status"] == "preparing"
    assert status["programme_id"] == episode["seed_id"]

    assert asyncio.run(api_module.generation_worker.run_once()) is True
    [status] = _status(client, headers, episode["id"])
    assert (status["status"], status["progress"]) == ("ready", 100)


def test_only_two_can_be_prepared_at_once_and_a_refusal_costs_no_allowance(
    jobs: InMemoryGenerationJobRepository,
) -> None:
    with TestClient(api_module.app) as client:
        headers = _headers()
        first = _prepared(client, headers)
        second = _prepared(client, headers)
        assert MAX_CONCURRENT_FULL_VERSIONS == 2
        refused = _prepare(client, headers)
        assert refused.status_code == 429
        assert "最多同时准备 2 档" in refused.json()["detail"]
        # The same episode asked for again is not a third one.
        assert client.post(f"/api/episodes/{first['id']}/materialize", headers=headers).status_code == 202
        # Someone else is not held up by this listener's two.
        other = _headers()
        assert _made(client, other, _prepare(client, other))["status"] == "ready"

        assert asyncio.run(api_module.generation_worker.run_once()) is True
        # One finished: a slot is free again.
        assert _prepare(client, headers).status_code == 202
        assert {item["episode_id"] for item in _status(client, headers, first["id"], second["id"])} == {first["id"], second["id"]}


def test_requests_still_being_made_hold_their_slots(
    jobs: InMemoryGenerationJobRepository, monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = api_module._make_proposals

    async def slow(body, owner):
        await asyncio.sleep(0.4)
        return await real(body, owner)

    monkeypatch.setattr(api_module, "_make_proposals", slow)
    with TestClient(api_module.app) as client:
        headers = _headers()
        accepted = [_prepare(client, headers), _prepare(client, headers)]
        # Neither has a programme yet, yet a third is already one too many.
        assert [item.status_code for item in accepted] == [202, 202]
        assert _prepare(client, headers).status_code == 429
        assert [_made(client, headers, item)["status"] for item in accepted] == ["ready", "ready"]


def test_a_request_that_cannot_be_made_says_why_and_is_only_visible_to_its_owner(
    jobs: InMemoryGenerationJobRepository, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def refuse(body, owner):
        raise HTTPException(status_code=429, detail="访客可以先创建 3 档节目。")

    monkeypatch.setattr(api_module, "_make_proposals", refuse)
    with TestClient(api_module.app) as client:
        headers = _headers()
        accepted = _prepare(client, headers)
        item = _made(client, headers, accepted)
        assert (item["status"], item["message"]) == ("failed", "访客可以先创建 3 档节目。")
        assert item["episode_id"] is None
        stranger = client.get(
            "/api/full-versions/requests", params={"ids": accepted.json()["request_id"]}, headers=_headers(),
        )
        assert stranger.json() == []


def test_status_is_only_given_to_the_owner(jobs: InMemoryGenerationJobRepository) -> None:
    with TestClient(api_module.app) as client:
        owner = _headers()
        episode = _prepared(client, owner)
        assert _status(client, _headers(), episode["id"], "no-such-episode") == []
        assert len(_status(client, owner, episode["id"], "no-such-episode")) == 1


def test_a_preparation_stalled_for_twenty_minutes_is_failed_frees_its_slot_and_can_be_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    age = [timedelta(minutes=21)]
    stale_jobs = InMemoryGenerationJobRepository(now=lambda: datetime.now(UTC) - age[0])
    monkeypatch.setattr(api_module, "generation_job_repository", stale_jobs)
    monkeypatch.setattr(api_module, "proposal_repository", InMemoryProgramProposalRepository())
    with TestClient(api_module.app) as client:
        headers = _headers()
        stalled = [_prepared(client, headers) for _ in range(2)]
        assert {item["status"] for item in _status(client, headers, *[e["id"] for e in stalled])} == {"failed"}

        # Neither counts against the limit any more, so a new one can start.
        assert _prepare(client, headers).status_code == 202

        # Retrying a stalled one starts it over with a fresh clock.
        age[0] = timedelta(0)
        retried = client.post(f"/api/episodes/{stalled[0]['id']}/materialize", headers=headers)
        assert retried.status_code == 202
        [item] = _status(client, headers, stalled[0]["id"])
        assert item["status"] == "preparing"
