import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from fastapi.testclient import TestClient
from wavecast.orchestration.worker import GenerationWorker, GenerationWorkerPolicy
from wavecast.storage import EpisodeConcurrencyError
from wavecast.storage.generation_jobs import (
    GenerationJobStatus,
    InMemoryGenerationJobRepository,
)

import services.api.main as api_module

app = api_module.app


def test_anonymous_listener_header_isolates_episode_access() -> None:
    client = TestClient(app)
    created = client.post(
        "/api/episodes/from-seed/city-pop-misunderstood",
        headers={"X-Wavecast-Listener": "listener-a"},
    ).json()

    denied = client.get(
        f"/api/episodes/{created['id']}", headers={"X-Wavecast-Listener": "listener-b"}
    )

    assert denied.status_code == 404


def test_sse_delivers_the_persisted_episode_snapshot(monkeypatch) -> None:
    jobs = InMemoryGenerationJobRepository()
    worker = GenerationWorker(jobs, api_module.orchestrator, worker_id="sse-test")
    monkeypatch.setattr(api_module, "generation_job_repository", jobs)
    monkeypatch.setattr(api_module, "generation_worker", worker)
    client = TestClient(app)
    headers = {"X-Wavecast-Listener": "sse-listener"}
    created = client.post("/api/episodes/from-seed/synthpop-return", headers=headers).json()
    assert asyncio.run(api_module.generation_worker.run_once()) is True

    with client.stream(
        "GET", f"/api/episodes/{created['id']}/events?once=true", headers=headers
    ) as response:
        lines = response.iter_lines()
        event = next(lines)
        assert next(lines) == "event: episode_state_changed"
        data = next(lines)
        next(lines)

    assert event.startswith("id: ")
    payload = json.loads(data.removeprefix("data: "))
    assert payload["id"] == created["id"]
    assert payload["version"] == int(event.removeprefix("id: "))
    assert payload["version"] >= 2


def test_concurrent_start_conflict_is_retryable_not_an_internal_error(monkeypatch) -> None:
    def start_conflict(*_args: object, **_kwargs: object) -> None:
        raise EpisodeConcurrencyError("duplicate listener and seed")

    monkeypatch.setattr(api_module.orchestrator, "start_or_resume", start_conflict)

    response = TestClient(app).post("/api/episodes/from-seed/city-pop-misunderstood")

    assert response.status_code == 409
    assert response.json()["detail"] == "Episode creation raced; retry"


def _complete_queued_job(jobs: InMemoryGenerationJobRepository, worker_id: str) -> None:
    claimed = jobs.claim(worker_id, lease_seconds=60)
    assert claimed is not None
    jobs.complete(claimed.id, worker_id, claimed.request_version)


def test_heartbeat_requeues_completed_generation_when_buffer_is_low(monkeypatch) -> None:
    jobs = InMemoryGenerationJobRepository()
    worker = GenerationWorker(
        jobs,
        api_module.orchestrator,
        worker_id="low-buffer-worker",
        policy=GenerationWorkerPolicy(target_ahead_seconds=1000),
    )
    monkeypatch.setattr(api_module, "generation_job_repository", jobs)
    monkeypatch.setattr(api_module, "generation_worker", worker)
    client = TestClient(app)
    headers = {"X-Wavecast-Listener": "low-buffer-listener"}

    created = client.post(
        "/api/episodes/from-seed/city-pop-misunderstood",
        headers=headers,
    ).json()
    _complete_queued_job(jobs, "complete-low-buffer")
    before = jobs.get_for_episode(created["id"])
    assert before is not None
    assert before.status is GenerationJobStatus.COMPLETED

    response = client.post(
        f"/api/episodes/{created['id']}/heartbeat",
        headers=headers,
    )

    assert response.status_code == 200
    queued = jobs.get_for_episode(created["id"])
    assert queued is not None
    assert queued.status is GenerationJobStatus.PENDING


def test_heartbeat_does_not_requeue_when_ready_audio_ahead_is_healthy(monkeypatch) -> None:
    # Isolate the healthy-buffer case from host filesystem/scheduling latency.
    # Slow observed generation is covered separately below.
    monkeypatch.setattr("wavecast.orchestration.episode.monotonic", lambda: 0.0)
    jobs = InMemoryGenerationJobRepository()
    worker = GenerationWorker(
        jobs,
        api_module.orchestrator,
        worker_id="healthy-buffer-worker",
        policy=GenerationWorkerPolicy(target_ahead_seconds=10),
    )
    monkeypatch.setattr(api_module, "generation_job_repository", jobs)
    monkeypatch.setattr(api_module, "generation_worker", worker)
    client = TestClient(app)
    headers = {"X-Wavecast-Listener": "healthy-buffer-listener"}

    created = client.post(
        "/api/episodes/from-seed/city-pop-misunderstood",
        headers=headers,
    ).json()
    assert asyncio.run(worker.run_once()) is True
    completed = jobs.get_for_episode(created["id"])
    assert completed is not None
    assert completed.status is GenerationJobStatus.COMPLETED

    response = client.post(
        f"/api/episodes/{created['id']}/heartbeat",
        headers=headers,
    )

    assert response.status_code == 200
    unchanged = jobs.get_for_episode(created["id"])
    assert unchanged is not None
    assert unchanged.status is GenerationJobStatus.COMPLETED


def test_healthy_heartbeat_throttles_recent_program_catchup(monkeypatch) -> None:
    monkeypatch.setattr(
        api_module,
        "buffer_decision",
        lambda *_args, **_kwargs: SimpleNamespace(needs_generation=False),
    )
    jobs = InMemoryGenerationJobRepository()
    monkeypatch.setattr(api_module, "generation_job_repository", jobs)
    monkeypatch.setattr(
        api_module.orchestrator,
        "needs_progressive_catchup",
        lambda _episode: True,
    )
    episode = api_module.orchestrator.start(
        api_module.SEEDS[0],
        listener_id="catchup-throttle-listener",
    )
    job = jobs.request(episode.id)
    claimed = jobs.claim("catchup-complete", lease_seconds=60)
    assert claimed is not None
    jobs.complete(claimed.id, "catchup-complete", claimed.request_version)

    api_module._queue_progressive_generation(episode)

    unchanged = jobs.get_for_episode(episode.id)
    assert unchanged is not None
    assert unchanged.status is GenerationJobStatus.COMPLETED
    assert unchanged.request_version == job.request_version


def test_healthy_heartbeat_requeues_stale_program_catchup(monkeypatch) -> None:
    monkeypatch.setattr(
        api_module,
        "buffer_decision",
        lambda *_args, **_kwargs: SimpleNamespace(needs_generation=False),
    )
    old_now = datetime.now(UTC) - timedelta(seconds=180)
    jobs = InMemoryGenerationJobRepository(now=lambda: old_now)
    monkeypatch.setattr(api_module, "generation_job_repository", jobs)
    monkeypatch.setattr(
        api_module.orchestrator,
        "needs_progressive_catchup",
        lambda _episode: True,
    )
    episode = api_module.orchestrator.start(
        api_module.SEEDS[1],
        listener_id="catchup-retry-listener",
    )
    jobs.request(episode.id)
    claimed = jobs.claim("catchup-old", lease_seconds=60)
    assert claimed is not None
    jobs.complete(claimed.id, "catchup-old", claimed.request_version)

    api_module._queue_progressive_generation(episode)

    queued = jobs.get_for_episode(episode.id)
    assert queued is not None
    assert queued.status is GenerationJobStatus.PENDING
    assert queued.request_version == claimed.request_version + 1


def test_heartbeat_refills_earlier_after_slow_generation(monkeypatch) -> None:
    jobs = InMemoryGenerationJobRepository()
    worker = GenerationWorker(jobs, api_module.orchestrator, worker_id="adaptive-buffer")
    monkeypatch.setattr(api_module, "generation_job_repository", jobs)
    monkeypatch.setattr(api_module, "generation_worker", worker)
    client = TestClient(app)
    headers = {"X-Wavecast-Listener": "adaptive-buffer-listener"}
    created = client.post("/api/episodes/from-seed/city-pop-misunderstood", headers=headers).json()
    assert asyncio.run(worker.run_once())
    episode = api_module.orchestrator.get(created["id"])
    assert episode.has_ready_successor
    successor = next(s for s in episode.ordered_segments if s.kind == "MUSIC" and s.id != episode.current_segment_id)
    episode.segments = [s for s in episode.segments if s.id == episode.current_segment_id or s.chapter_id == successor.chapter_id]
    episode.generation_latency_seconds = 400
    api_module.orchestrator.repository.save(episode)
    response = client.post(f"/api/episodes/{episode.id}/heartbeat", headers=headers)
    assert response.status_code == 200
    queued = jobs.get_for_episode(episode.id)
    assert queued is not None
    assert queued.status is GenerationJobStatus.PENDING


def test_heartbeat_does_not_revive_failed_job_but_explicit_retry_does(monkeypatch) -> None:
    jobs = InMemoryGenerationJobRepository()
    worker = GenerationWorker(
        jobs,
        api_module.orchestrator,
        worker_id="failed-buffer-worker",
        policy=GenerationWorkerPolicy(target_ahead_seconds=1000),
    )
    monkeypatch.setattr(api_module, "generation_job_repository", jobs)
    monkeypatch.setattr(api_module, "generation_worker", worker)
    client = TestClient(app)
    headers = {"X-Wavecast-Listener": "failed-buffer-listener"}

    created = client.post(
        "/api/episodes/from-seed/city-pop-misunderstood",
        headers=headers,
    ).json()
    claimed = jobs.claim("fail-worker", lease_seconds=60)
    assert claimed is not None
    jobs.fail(
        claimed.id,
        "fail-worker",
        claimed.request_version,
        error_code="provider_configuration",
    )

    heartbeat_response = client.post(
        f"/api/episodes/{created['id']}/heartbeat",
        headers=headers,
    )
    assert heartbeat_response.status_code == 200
    failed = jobs.get_for_episode(created["id"])
    assert failed is not None
    assert failed.status is GenerationJobStatus.FAILED

    retry_response = client.post(
        f"/api/episodes/{created['id']}/ensure-buffer",
        headers=headers,
        json={"target_chapters": 1},
    )
    assert retry_response.status_code == 200
    retried = jobs.get_for_episode(created["id"])
    assert retried is not None
    assert retried.status is GenerationJobStatus.PENDING
    assert retried.last_error_code is None
