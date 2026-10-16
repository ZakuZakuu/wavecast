"""Provider usage kept beyond the process: stored per episode, read back after a restart, once.

Offline.  Costs are reported per currency; a call with no figure is unknown, never zero.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from wavecast.providers.config import ProviderSettings
from wavecast.providers.errors import ProviderBudgetExceededError
from wavecast.providers.search import ExaSearchProvider, TavilySearchProvider
from wavecast.providers.usage import (
    UsageEvent,
    UsageLedger,
    cost_summary,
    diagnostics_of,
    merge_events,
    usage_scope,
)
from wavecast.storage import LocalObjectStorageProvider
from wavecast.storage.usage_events import (
    MAX_EVENTS_PER_SCOPE,
    UsageEventsError,
    UsageEventStore,
    usage_events_key,
)

from services.api import main as api_module


def event(provider: str = "ark", stage: str = "writer", **fields: object) -> UsageEvent:
    metadata = fields.pop("metadata", {"stage": stage})
    return UsageEvent(provider=provider, operation="op", elapsed_ms=10, metadata=metadata, **fields)  # type: ignore[arg-type]


@pytest.fixture
def storage(tmp_path) -> LocalObjectStorageProvider:  # type: ignore[no-untyped-def]
    return LocalObjectStorageProvider(tmp_path / "store")


# --- the store -------------------------------------------------------------------------------------


def test_events_are_stored_per_scope_and_read_back_by_a_new_store(storage) -> None:  # type: ignore[no-untyped-def]
    async def scenario() -> None:
        store = UsageEventStore(storage)
        with usage_scope("ep-1"):
            first, second = event(input_tokens=5), event("exa", "background_research", actual_cost_usd=0.007)
        with usage_scope("ep-2"):
            other = event()
        for item in (first, second, other):
            await store.append(item.scope or "", item)

        restarted = UsageEventStore(storage)  # a new process: nothing in memory
        loaded = await restarted.load("ep-1")

        assert [e.event_id for e in loaded] == [first.event_id, second.event_id]
        assert loaded[1].actual_cost_usd == 0.007 and loaded[0].scope == "ep-1"
        assert [e.event_id for e in await restarted.load("ep-2")] == [other.event_id]
        assert await restarted.load("never-used") == []

    asyncio.run(scenario())


def test_the_same_call_written_twice_is_stored_once_and_the_log_is_capped(storage) -> None:  # type: ignore[no-untyped-def]
    async def scenario() -> None:
        store = UsageEventStore(storage)
        one = event()
        await store.append("ep", one)
        await store.append("ep", one)
        assert len(await store.load("ep")) == 1
        await asyncio.gather(*(store.append("ep", event()) for _ in range(MAX_EVENTS_PER_SCOPE + 5)))
        assert len(await store.load("ep")) == MAX_EVENTS_PER_SCOPE  # concurrent appends lose nothing under the cap

    asyncio.run(scenario())


def test_damaged_or_unversioned_stored_usage_is_refused_not_guessed(storage) -> None:  # type: ignore[no-untyped-def]
    async def scenario() -> None:
        store = UsageEventStore(storage)
        for payload in (b"{not json", json.dumps({"events": []}).encode(), json.dumps({"schema_version": 2, "events": []}).encode()):
            await storage.put(usage_events_key("ep"), payload, "application/json")
            with pytest.raises(UsageEventsError):
                await store.load("ep")
        with pytest.raises(ValueError):
            usage_events_key("../escape")

    asyncio.run(scenario())


# --- the ledger writes through, and a broken sink never breaks a call -----------------------------------


def test_a_scoped_event_is_persisted_and_an_unscoped_one_is_not(storage) -> None:  # type: ignore[no-untyped-def]
    async def scenario() -> None:
        ledger, store = UsageLedger(), UsageEventStore(storage)
        ledger.attach_sink(store)
        with usage_scope("ep-1"):
            ledger.record(event(input_tokens=3))
        ledger.record(event())  # no scope: nothing to file it under
        await ledger.flush()

        assert [e.input_tokens for e in await UsageEventStore(storage).load("ep-1")] == [3]

    asyncio.run(scenario())


def test_a_failing_sink_is_logged_and_never_raises(caplog: pytest.LogCaptureFixture) -> None:
    class Broken:
        async def append(self, scope: str, item: UsageEvent) -> None:
            raise OSError("disk full")

    async def scenario() -> UsageLedger:
        ledger = UsageLedger()
        ledger.attach_sink(Broken())
        with usage_scope("ep"):
            ledger.record(event())
        await ledger.flush()
        return ledger

    ledger = asyncio.run(scenario())

    assert len(ledger.events) == 1  # the in-memory record is intact
    assert "usage_event_not_persisted error_type=OSError" in caplog.text


def test_recording_outside_a_running_loop_keeps_the_event_in_memory_only(caplog: pytest.LogCaptureFixture, storage) -> None:  # type: ignore[no-untyped-def]
    ledger = UsageLedger()
    ledger.attach_sink(UsageEventStore(storage))
    with usage_scope("ep"):
        ledger.record(event())

    assert len(ledger.events) == 1 and "no_running_loop" in caplog.text


# --- merging and costs ------------------------------------------------------------------------------------


def test_merging_the_live_ledger_with_its_stored_copy_counts_each_call_once() -> None:
    a, b, c = event(), event(), event()
    merged = merge_events([a, b], [b.model_copy(), c])

    assert [e.event_id for e in merged] == [a.event_id, b.event_id, c.event_id]


def test_costs_are_per_currency_and_unknown_calls_are_listed_not_zeroed() -> None:
    events = [
        event(metadata={"stage": "writer", "estimated_cost_cny": 0.25, "outcome": "ok"}),
        event(metadata={"stage": "dialogue_speech", "estimated_cost_cny": 0.0, "outcome": "ok"}),  # a reported zero
        event("exa", "background_research", actual_cost_usd=0.007, metadata={"stage": "background_research", "outcome": "ok"}),
        event("tavily", "background_research", search_credits=2.0, metadata={"stage": "background_research"}),
        event("exa", "background_research", metadata={"stage": "background_research", "outcome": "error", "cost_basis": "no_receipt"}),
        event("ark", "story_material", metadata={"stage": "story_material", "outcome": "timeout", "estimated_cost_cny": None}),
    ]

    summary = cost_summary(events)

    assert summary["cny"] == {"estimated": 0.25, "priced_calls": 2}
    assert summary["usd"] == {"charged_or_estimated": 0.007, "priced_calls": 1}
    assert summary["search_credits"] == {"reported": 2.0, "calls": 1}
    assert [(u["provider"], u["outcome"]) for u in summary["unknown_calls"]] == [("exa", "error"), ("ark", "timeout")]
    assert "never converted" in summary["note"]


# --- search failures and cancellations are recorded -----------------------------------------------------------


def _exa(handler, ledger):  # type: ignore[no-untyped-def]
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    settings = ProviderSettings(mode="live", exa_api_key="k", tavily_api_key="k", max_attempts=1)
    return client, ExaSearchProvider(settings, client=client, ledger=ledger)


def test_a_failed_search_leaves_an_event_with_the_error_and_no_cost() -> None:
    async def scenario() -> UsageLedger:
        ledger = UsageLedger()
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(432, json={"detail": "plan limit"})))
        provider = TavilySearchProvider(
            ProviderSettings(mode="live", tavily_api_key="k", max_attempts=1), client=client, ledger=ledger
        )
        with usage_scope("ep"), pytest.raises(ProviderBudgetExceededError):
            await provider.search("q", stage="background_research")
        await client.aclose()
        return ledger

    (failed,) = asyncio.run(scenario()).events

    assert (failed.provider, failed.operation, failed.scope, failed.search_queries) == ("tavily", "search", "ep", 1)
    assert failed.metadata["outcome"] == "error" and failed.metadata["error_type"] == "ProviderBudgetExceededError"
    assert failed.metadata["stage"] == "background_research" and failed.metadata["cost_basis"] == "no_receipt"
    assert failed.search_credits is None and failed.actual_cost_usd is None  # unknown, not zero


def test_a_cancelled_search_is_recorded_and_the_cancellation_still_propagates() -> None:
    async def scenario() -> UsageLedger:
        ledger = UsageLedger()
        started = asyncio.Event()

        async def slow(_request: httpx.Request) -> httpx.Response:
            started.set()
            await asyncio.sleep(30)
            return httpx.Response(200, json={})

        client, provider = _exa(slow, ledger)
        with usage_scope("ep"):
            task = asyncio.create_task(provider.search("q", stage="track_research"))
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        await client.aclose()
        return ledger

    (cancelled,) = asyncio.run(scenario()).events

    assert cancelled.metadata["outcome"] == "cancelled" and cancelled.metadata["stage"] == "track_research"
    assert cancelled.actual_cost_usd is None


def test_a_successful_search_says_so() -> None:
    async def scenario() -> UsageEvent:
        ledger = UsageLedger()
        client, provider = _exa(lambda r: httpx.Response(200, json={"results": [], "costDollars": {"total": 0.007}}), ledger)
        await provider.search("q")
        await client.aclose()
        return ledger.events[0]

    done = asyncio.run(scenario())

    assert done.metadata["outcome"] == "ok" and done.actual_cost_usd == 0.007


# --- the endpoint survives a restart --------------------------------------------------------------------------------


def test_the_usage_endpoint_still_answers_after_a_restart_and_counts_each_call_once() -> None:
    client = TestClient(api_module.app)
    owner = {"X-Wavecast-Listener": "usage-restart-owner"}
    created = client.post("/api/episodes/from-seed/synthpop-return", headers=owner).json()
    episode_id = created["id"]
    with usage_scope(episode_id):
        live = event("exa", "background_research", actual_cost_usd=0.007, metadata={"stage": "background_research", "outcome": "ok"})
        gone = event("ark", "writer", metadata={"stage": "writer", "outcome": "ok", "estimated_cost_cny": 0.5}, input_tokens=100)
    # "gone" was written before a restart (only its stored copy remains); "live" is in both places.
    asyncio.run(api_module._usage_event_store.append(episode_id, gone))  # noqa: SLF001
    asyncio.run(api_module._usage_event_store.append(episode_id, live))  # noqa: SLF001
    api_module._usage_ledger().record(live)  # noqa: SLF001  # asyncio loop-less: memory only

    body = client.get(f"/api/episodes/{episode_id}/usage", headers=owner).json()

    assert body["stored_events"] == 2
    assert body["providers"]["usage"]["event_count"] == 2  # not 3: the live call is counted once
    assert body["costs"]["cny"]["estimated"] == 0.5 and body["costs"]["usd"]["charged_or_estimated"] == 0.007
    assert {e["event_id"] for e in body["providers"]["provider_events"]} == {live.event_id, gone.event_id}
    assert diagnostics_of([live, gone])["usage"]["event_count"] == 2


def test_the_usage_endpoint_reads_the_episode_off_the_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    # PostgresEpisodeRepository answers synchronously with asyncio.run(), which fails on a running loop.
    client = TestClient(api_module.app)
    owner = {"X-Wavecast-Listener": "usage-thread-owner"}
    created = client.post("/api/episodes/from-seed/synthpop-return", headers=owner).json()
    original = api_module.orchestrator.get
    on_loop: list[str] = []

    def get(episode_id: str):  # type: ignore[no-untyped-def]
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return original(episode_id)
        on_loop.append(episode_id)
        raise RuntimeError("asyncio.run() cannot be called from a running event loop")

    monkeypatch.setattr(api_module.orchestrator, "get", get)

    response = client.get(f"/api/episodes/{created['id']}/usage", headers=owner)

    assert response.status_code == 200 and on_loop == []


def test_the_usual_projection_keeps_its_shape_and_the_episode_report_adds_ids() -> None:
    one = event()

    plain = diagnostics_of([one])["provider_events"][0]
    with_ids = diagnostics_of([one], with_ids=True)["provider_events"][0]

    assert "event_id" not in plain and "recorded_at" not in plain
    assert with_ids["event_id"] == one.event_id and with_ids["recorded_at"] == one.recorded_at.isoformat()
    assert {k: v for k, v in with_ids.items() if k not in {"event_id", "recorded_at"}} == plain
