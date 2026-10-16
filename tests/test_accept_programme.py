"""The acceptance listener keeps its lease the way the web player does, without any real provider.

A whole-programme run once lost its listener lease because the script waited for a ~34 s
``program-render`` before sending the next heartbeat (the server drops the lease after 30 s).  The web
player sends heartbeats from a timer of its own and takes the lease back on a 409.  Here a fake server
stands in for the API: the timings are scaled down, the behaviour under test is the same.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "accept_programme.py"


@pytest.fixture(scope="module")
def harness() -> Any:
    spec = importlib.util.spec_from_file_location("accept_programme_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeApi:
    """Just enough of the API for one programme: it records what the listener sends and when."""

    def __init__(self, *, render_seconds: float, lease_lapses_after: float | None = None) -> None:
        self.render_seconds = render_seconds
        self.lease_lapses_after = lease_lapses_after
        self.started = time.monotonic()
        self.heartbeats: list[float] = []
        self.checkpoints: list[tuple[float, float]] = []
        self.resumes = 0
        self.renders = 0
        self.completed = 0
        self.lease_active = True
        self.published = False

    def now(self) -> float:
        return time.monotonic() - self.started

    async def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/program-proposals":
            return httpx.Response(200, json={"proposals": [{"id": "p1", "title": "t", "estimated_duration_seconds": 5,
                                                              "opening_track_artist": "a", "opening_track_title": "b"}]})
        if path.startswith("/api/episodes/from-seed/"):
            return httpx.Response(200, json={"id": "e1", "program_estimated_duration_seconds": 5})
        if path == "/api/episodes/e1/heartbeat":
            self.heartbeats.append(self.now())
            if self.lease_lapses_after is not None and self.now() >= self.lease_lapses_after:
                self.lease_active = False
            return httpx.Response(200 if self.lease_active else 409, json={})
        if path == "/api/episodes/e1/resume":
            self.resumes += 1
            await asyncio.sleep(0.15)
            self.lease_active = True
            self.lease_lapses_after = None
            return httpx.Response(200, json={})
        if path == "/api/episodes/e1/program-playback-checkpoint":
            self.checkpoints.append((self.now(), 0.0))
            return httpx.Response(200, json={})
        if path == "/api/episodes/e1/program-render":
            self.renders += 1
            await asyncio.sleep(self.render_seconds)
            self.published = True
            return httpx.Response(200, json={"renderedFrontierSeconds": 3.0, "complete": True, "chunks": [1, 2]})
        if path == "/api/episodes/e1/completed":
            self.completed += 1
            return httpx.Response(200, json={})
        if path == "/api/episodes/e1":
            return httpx.Response(200, json={"state": "STREAMING", "version": 1, "segments": []})
        return httpx.Response(404)


async def run_drive(harness: Any, tmp_path: Path, api: FakeApi, events: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    harness.job_failed = lambda _episode_id: _none()
    client = httpx.AsyncClient(transport=httpx.MockTransport(api.handle), base_url="http://fake")
    meter = harness.Meter()
    try:
        return await harness.drive(
            client, meter, tmp_path, lambda event, **data: events.append((event, data)),
            speed=1.0, heartbeat_seconds=0.05, checkpoint_seconds=0.1, poll_seconds=0.05, render_retry_seconds=5.0,
        )
    finally:
        await client.aclose()


async def _none() -> None:
    return None


def test_heartbeats_keep_flowing_while_a_render_takes_longer_than_the_lease(harness, tmp_path) -> None:  # type: ignore[no-untyped-def]
    # 0.6 s of render stands in for ~34 s; the lease (30 s) stands in for 0.3 s: a heartbeat gap longer
    # than that would have lost it.  The listener must keep beating every ~0.05 s through the render.
    api = FakeApi(render_seconds=0.6)
    events: list[tuple[str, dict[str, Any]]] = []

    result = asyncio.run(run_drive(harness, tmp_path, api, events))

    assert result["status"] == "completed", result
    assert api.renders >= 1
    gaps = [b - a for a, b in zip(api.heartbeats, api.heartbeats[1:], strict=False)]
    assert len(api.heartbeats) >= 8
    assert max(gaps) < 0.3, f"a heartbeat gap of {max(gaps):.2f}s would have lost the lease"
    assert len(api.checkpoints) >= 2  # the position is reported on its own timer too


def test_a_lapsed_lease_is_taken_back_once(harness, tmp_path) -> None:  # type: ignore[no-untyped-def]
    api = FakeApi(render_seconds=0.4, lease_lapses_after=0.1)
    events: list[tuple[str, dict[str, Any]]] = []

    result = asyncio.run(run_drive(harness, tmp_path, api, events))

    assert result["status"] == "completed", result
    assert api.resumes == 1
    assert result["lease_lost"] == 1 and result["lease_recovered"] == 1
    assert [name for name, _ in events if name.startswith("lease")] == ["lease_lost", "lease_recovered"]


def test_the_background_tasks_stop_with_the_run(harness, tmp_path) -> None:  # type: ignore[no-untyped-def]
    api = FakeApi(render_seconds=0.1)
    events: list[tuple[str, dict[str, Any]]] = []

    async def scenario() -> tuple[int, int]:
        await run_drive(harness, tmp_path, api, events)
        before = len(api.heartbeats)
        await asyncio.sleep(0.3)
        pending = [t for t in asyncio.all_tasks() if t.get_name() in {"heartbeat", "checkpoint", "program-render"}]
        return len(api.heartbeats) - before, len(pending)

    late_heartbeats, leftover = asyncio.run(scenario())

    assert late_heartbeats == 0
    assert leftover == 0


def test_a_stopped_run_does_not_take_the_lease_back(harness, tmp_path) -> None:  # type: ignore[no-untyped-def]
    api = FakeApi(render_seconds=0.2, lease_lapses_after=0.05)
    events: list[tuple[str, dict[str, Any]]] = []

    async def scenario() -> dict[str, Any]:
        harness.job_failed = lambda _episode_id: _none()
        client = httpx.AsyncClient(transport=httpx.MockTransport(api.handle), base_url="http://fake")
        meter = harness.Meter()
        meter.frozen = True  # a failure has stopped the run: no more paid calls, so no resume either
        # the run itself never completes (the fake keeps answering 409), so bound it
        try:
            return await asyncio.wait_for(
                harness.drive(
                    client, meter, tmp_path, lambda event, **data: events.append((event, data)),
                    speed=1.0, heartbeat_seconds=0.05, checkpoint_seconds=0.1, poll_seconds=0.05,
                    render_retry_seconds=5.0,
                ),
                timeout=1.5,
            )
        except TimeoutError:
            return {"status": "bounded"}
        finally:
            await client.aclose()

    asyncio.run(scenario())

    assert api.resumes == 0
    assert any(name == "lease_not_recovered" for name, _ in events)


def test_two_recoveries_at_once_resume_only_once(harness) -> None:  # type: ignore[no-untyped-def]
    api = FakeApi(render_seconds=0.0)

    async def scenario() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(api.handle), base_url="http://fake")
        listener = harness.Listener(client, harness.Meter(), lambda *_a, **_k: None, "e1")
        await asyncio.gather(listener.recover(), listener.recover())
        await client.aclose()

    asyncio.run(scenario())

    assert api.resumes == 1


def test_a_failed_paid_call_stops_every_later_paid_call(harness) -> None:  # type: ignore[no-untyped-def]
    meter = harness.Meter()

    async def scenario() -> tuple[str, str | None]:
        try:
            async with meter.permit("ark", cny=0.1):
                raise RuntimeError("provider failed")
        except RuntimeError as error:
            first = str(error)  # the failure still reaches its caller
        try:
            async with meter.permit("exa", usd=0.01):
                return first, "allowed"
        except harness.BudgetStop:
            return first, None

    first, second = asyncio.run(scenario())

    assert first == "provider failed"
    assert second is None  # the next paid call was refused
    assert meter.tripped == "ark_failed"
    assert meter.denied["exa"] == 1
    assert meter.inflight_cny == 0  # the reservation was released


def test_a_cancelled_paid_call_stops_later_paid_calls_and_the_cancellation_propagates(harness) -> None:  # type: ignore[no-untyped-def]
    meter = harness.Meter()

    async def scenario() -> bool:
        async def slow() -> None:
            async with meter.permit("doubao", cny=0.6):
                await asyncio.sleep(10)

        task = asyncio.create_task(slow())
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            return True
        return False

    assert asyncio.run(scenario()) is True
    assert meter.tripped == "doubao_cancelled"

    async def later() -> bool:
        try:
            async with meter.permit("ark", cny=0.01):
                return True
        except harness.BudgetStop:
            return False

    assert asyncio.run(later()) is False


def test_a_successful_paid_call_does_not_stop_the_run(harness) -> None:  # type: ignore[no-untyped-def]
    meter = harness.Meter()

    async def scenario() -> None:
        async with meter.permit("ark", cny=0.1):
            pass
        async with meter.permit("ark", cny=0.1):
            pass

    asyncio.run(scenario())

    assert meter.tripped is None
    assert meter.calls["ark"] == 2
