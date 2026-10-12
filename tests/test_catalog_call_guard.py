import asyncio

import httpx
import pytest
from wavecast.intelligence.models import ResolvedTrack
from wavecast.providers.call_guard import CatalogCallGuard
from wavecast.providers.config import ProviderSettings
from wavecast.providers.errors import (
    ProviderInvalidResponseError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from wavecast.providers.netease import NeteaseMusicProvider


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Counter:
    def __init__(self, result: object = None, error: Exception | None = None) -> None:
        self.calls = 0
        self.result = {"ok": True} if result is None else result
        self.error = error

    async def __call__(self) -> object:
        self.calls += 1
        await asyncio.sleep(0)
        if self.error is not None:
            raise self.error
        return self.result


def guard(clock: Clock | None = None, **kwargs: float) -> CatalogCallGuard:
    return CatalogCallGuard(clock=clock or Clock(), **kwargs)  # type: ignore[arg-type]


# --- cache -------------------------------------------------------------------------------


def test_a_successful_lookup_is_cached_until_it_expires() -> None:
    clock = Clock()
    g = guard(clock)
    factory = Counter()

    async def run() -> None:
        await g.call("k", 60, factory)
        await g.call("k", 60, factory)
        assert factory.calls == 1
        clock.now += 61
        await g.call("k", 60, factory)

    asyncio.run(run())

    assert factory.calls == 2


def test_cached_results_are_isolated_copies() -> None:
    g = guard()
    factory = Counter(result={"tracks": [1]})

    async def run() -> None:
        miss = await g.call("k", 60, factory)
        miss["tracks"].append("from-miss")  # mutating a fresh result must not poison the cache
        hit = await g.call("k", 60, factory)
        assert hit == {"tracks": [1]}
        hit["tracks"].append("from-hit")  # nor must mutating a cached result
        assert await g.call("k", 60, factory) == {"tracks": [1]}

    asyncio.run(run())

    assert factory.calls == 1


def test_different_keys_are_cached_separately_and_zero_ttl_is_not_cached() -> None:
    g = guard()
    a, b, c = Counter(), Counter(), Counter()

    async def run() -> None:
        await g.call("a", 60, a)
        await g.call("b", 60, b)
        await g.call("a", 60, a)
        await g.call("c", 0, c)
        await g.call("c", 0, c)

    asyncio.run(run())

    assert (a.calls, b.calls, c.calls) == (1, 1, 2)


def test_the_cache_is_bounded_and_evicts_the_least_recently_used_entry() -> None:
    g = guard(max_entries=2)
    counters = {key: Counter() for key in "abc"}

    async def run() -> None:
        await g.call("a", 60, counters["a"])
        await g.call("b", 60, counters["b"])
        await g.call("a", 60, counters["a"])  # a is now the most recently used
        await g.call("c", 60, counters["c"])  # evicts b
        await g.call("a", 60, counters["a"])
        await g.call("b", 60, counters["b"])

    asyncio.run(run())

    assert counters["a"].calls == 1
    assert counters["b"].calls == 2


# --- coalescing --------------------------------------------------------------------------


def test_identical_concurrent_lookups_share_one_request() -> None:
    g = guard()
    factory = Counter()

    async def run() -> list[object]:
        return await asyncio.gather(*(g.call("k", 60, factory) for _ in range(6)))

    results = asyncio.run(run())

    assert factory.calls == 1
    assert results == [{"ok": True}] * 6


def test_waiters_share_a_failure_and_it_is_not_cached() -> None:
    g = guard()
    factory = Counter(error=ProviderUnavailableError("down"))

    async def run() -> None:
        outcomes = await asyncio.gather(
            *(g.call("k", 60, factory) for _ in range(3)), return_exceptions=True
        )
        assert all(isinstance(item, ProviderUnavailableError) for item in outcomes)
        factory.error = None
        assert await g.call("k", 60, factory) == {"ok": True}

    asyncio.run(run())

    assert factory.calls == 2


def test_a_cancelled_owner_does_not_cancel_its_waiters() -> None:
    g = guard()
    release = asyncio.Event

    async def run() -> None:
        started = release()
        gate = release()

        async def slow() -> object:
            started.set()
            await gate.wait()
            return {"ok": True}

        owner = asyncio.create_task(g.call("k", 60, slow))
        await started.wait()
        waiter = asyncio.create_task(g.call("k", 60, slow))
        await asyncio.sleep(0)
        owner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await owner
        with pytest.raises(ProviderUnavailableError):
            await waiter

    asyncio.run(run())


# --- circuit breaker ---------------------------------------------------------------------


def test_the_breaker_opens_after_consecutive_transient_failures_and_fails_fast() -> None:
    clock = Clock()
    g = guard(clock, failure_threshold=3, cooldown_seconds=60)
    failing = Counter(error=ProviderUnavailableError("risk control"))
    other = Counter()

    async def run() -> None:
        for index in range(3):
            with pytest.raises(ProviderUnavailableError):
                await g.call(f"k{index}", 60, failing)
        assert g.is_open
        with pytest.raises(ProviderUnavailableError, match="paused"):
            await g.call("another", 60, other)

    asyncio.run(run())

    assert failing.calls == 3
    assert other.calls == 0  # no request was sent while the circuit was open


def test_cached_results_are_still_served_while_the_breaker_is_open() -> None:
    g = guard(failure_threshold=1)
    good, bad = Counter(), Counter(error=ProviderTimeoutError("slow"))

    async def run() -> None:
        await g.call("cached", 60, good)
        with pytest.raises(ProviderTimeoutError):
            await g.call("other", 60, bad)
        assert g.is_open
        assert await g.call("cached", 60, good) == {"ok": True}

    asyncio.run(run())

    assert good.calls == 1


def test_after_the_cooldown_one_failure_reopens_and_a_success_closes() -> None:
    clock = Clock()
    g = guard(clock, failure_threshold=2, cooldown_seconds=30)
    bad = Counter(error=ProviderRateLimitError("slow down"))
    good = Counter()

    async def run() -> None:
        for index in range(2):
            with pytest.raises(ProviderRateLimitError):
                await g.call(f"a{index}", 60, bad)
        assert g.is_open
        clock.now += 31
        assert not g.is_open
        with pytest.raises(ProviderRateLimitError):
            await g.call("probe", 60, bad)  # half-open: a single failure reopens
        assert g.is_open
        clock.now += 31
        assert await g.call("recover", 60, good) == {"ok": True}
        assert not g.is_open
        # Counting restarts from zero after a success.
        with pytest.raises(ProviderRateLimitError):
            await g.call("again", 60, bad)
        assert not g.is_open

    asyncio.run(run())


def test_non_transient_errors_never_open_the_breaker() -> None:
    g = guard(failure_threshold=1)
    unknown = Counter(error=ProviderInvalidResponseError("no such track"))

    async def run() -> None:
        for index in range(4):
            with pytest.raises(ProviderInvalidResponseError):
                await g.call(f"k{index}", 60, unknown)

    asyncio.run(run())

    assert not g.is_open
    assert unknown.calls == 4


def test_a_success_between_failures_resets_the_count() -> None:
    g = guard(failure_threshold=3)
    bad = Counter(error=ProviderUnavailableError("blip"))
    good = Counter()

    async def run() -> None:
        for step in range(2):
            with pytest.raises(ProviderUnavailableError):
                await g.call(f"bad{step}", 60, bad)
        await g.call("good", 60, good)
        for step in range(2):
            with pytest.raises(ProviderUnavailableError):
                await g.call(f"bad-again{step}", 60, bad)

    asyncio.run(run())

    assert not g.is_open


@pytest.mark.parametrize(
    "kwargs",
    [{"failure_threshold": 0}, {"cooldown_seconds": 0}, {"max_entries": 0}],
)
def test_invalid_guard_settings_are_rejected(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        CatalogCallGuard(**kwargs)  # type: ignore[arg-type]


# --- sidecar integration -----------------------------------------------------------------

BASE = "https://netease.sidecar"
TRACK = {"id": "t1", "artist": "A", "title": "T", "duration_seconds": 200, "playable": True}


def sidecar(handler, **kwargs: object) -> tuple[NeteaseMusicProvider, httpx.AsyncClient]:  # type: ignore[no-untyped-def]
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=BASE)
    return NeteaseMusicProvider(ProviderSettings(), client=client, base_url=BASE, **kwargs), client  # type: ignore[arg-type]


def test_sidecar_repeats_of_the_same_search_and_detail_send_one_request_each() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/search":
            return httpx.Response(200, json={"tracks": [TRACK]})
        return httpx.Response(200, json={"data": TRACK})

    async def run() -> None:
        provider, client = sidecar(handler)
        for _ in range(3):
            await provider.search("A T", limit=5)
            await provider.resolve_track("netease:t1")
        await client.aclose()

    asyncio.run(run())

    assert paths == ["/search", "/tracks/t1"]


def test_sidecar_playback_urls_are_never_cached() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("/playback"):
            return httpx.Response(200, json={"data": {"playback_url": f"{BASE}/stream/t1"}})
        return httpx.Response(200, json={"data": TRACK})

    async def run() -> None:
        provider, client = sidecar(handler)
        resolved = ResolvedTrack(track_ref="netease:t1", canonical_artist="A", canonical_title="T")
        await provider.resolve_upstream_playback_url(resolved.track_ref)
        await provider.resolve_upstream_playback_url(resolved.track_ref)
        await client.aclose()

    asyncio.run(run())

    assert paths.count("/tracks/t1/playback") == 2
    assert paths.count("/tracks/t1") == 1  # only the metadata lookup is cached


def test_sidecar_stops_sending_requests_while_the_upstream_keeps_failing() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(502, json={"detail": "music upstream unavailable"})

    async def run() -> None:
        provider, client = sidecar(handler, guard=CatalogCallGuard(failure_threshold=3))
        for index in range(6):
            with pytest.raises(ProviderUnavailableError):
                await provider.search(f"query {index}", limit=5)
        await client.aclose()

    asyncio.run(run())

    assert len(paths) == 3  # the breaker opened after the third failure
