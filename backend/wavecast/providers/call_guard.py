"""Short-lived cache, request coalescing and a circuit breaker for catalog sidecar calls.

The music upstream is an external service that can rate-limit or risk-control a client
for a few minutes (observed 2026-10-08: ``code -460``).  Repeating identical lookups or
hammering it while it refuses makes that worse.  The guard therefore

* caches successful lookups briefly (metadata only, never playback URLs),
* coalesces identical in-flight lookups into one request, and
* opens a circuit after consecutive transient failures, failing fast for a cooldown
  instead of sending more requests.

Failures are never cached, and only transient errors (unavailable, timeout, rate limit)
count towards the breaker: an unknown track or a malformed response is not an outage.
"""

from __future__ import annotations

import asyncio
import copy
import threading
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Hashable
from time import monotonic
from typing import Any

from .errors import (
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

_TRANSIENT = (ProviderUnavailableError, ProviderTimeoutError, ProviderRateLimitError)


class CatalogCallGuard:
    """Thread-safe cache and breaker; in-flight coalescing is scoped to one event loop."""

    def __init__(
        self,
        *,
        failure_threshold: int = 3,
        cooldown_seconds: float = 60.0,
        max_entries: int = 512,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be at least 1")
        if cooldown_seconds <= 0:
            raise ValueError("cooldown_seconds must be positive")
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.max_entries = max_entries
        self._clock = clock
        self._lock = threading.Lock()
        self._cache: OrderedDict[Hashable, tuple[float, Any]] = OrderedDict()
        self._failures = 0
        self._open_until = 0.0
        self._inflight: dict[tuple[int, Hashable], asyncio.Future[Any]] = {}

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._clock() < self._open_until

    async def call(
        self,
        key: Hashable,
        ttl_seconds: float,
        factory: Callable[[], Awaitable[Any]],
    ) -> Any:
        """Return a cached result, join an identical in-flight call, or run ``factory``."""

        cached = self._lookup(key)
        if cached is not _MISSING:
            return copy.deepcopy(cached)
        self._raise_if_open()

        loop = asyncio.get_running_loop()
        flight_key = (id(loop), key)
        waiting = self._inflight.get(flight_key)
        if waiting is not None:
            return copy.deepcopy(await asyncio.shield(waiting))

        future: asyncio.Future[Any] = loop.create_future()
        self._inflight[flight_key] = future
        try:
            result = await factory()
        except asyncio.CancelledError:
            # A cancelled owner must not cancel unrelated waiters; they see a transient error.
            future.set_exception(ProviderUnavailableError("catalog lookup was cancelled"))
            future.exception()
            raise
        except Exception as error:
            self._record_failure(error)
            future.set_exception(error)
            # Waiters re-raise it; mark it retrieved so an unawaited future stays quiet.
            future.exception()
            raise
        else:
            self._record_success()
            self._store(key, ttl_seconds, result)
            future.set_result(result)
            return copy.deepcopy(result)
        finally:
            self._inflight.pop(flight_key, None)

    def _lookup(self, key: Hashable) -> Any:
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return _MISSING
            expires_at, value = entry
            if self._clock() >= expires_at:
                del self._cache[key]
                return _MISSING
            self._cache.move_to_end(key)
            return value

    def _store(self, key: Hashable, ttl_seconds: float, value: Any) -> None:
        if ttl_seconds <= 0:
            return
        with self._lock:
            self._cache[key] = (self._clock() + ttl_seconds, copy.deepcopy(value))
            self._cache.move_to_end(key)
            while len(self._cache) > self.max_entries:
                self._cache.popitem(last=False)

    def _raise_if_open(self) -> None:
        with self._lock:
            if self._clock() < self._open_until:
                raise ProviderUnavailableError(
                    "music catalog is paused after repeated failures; try again shortly"
                )

    def _record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._open_until = 0.0

    def _record_failure(self, error: Exception) -> None:
        if not isinstance(error, _TRANSIENT):
            return
        with self._lock:
            self._failures += 1
            if self._failures >= self.failure_threshold:
                self._open_until = self._clock() + self.cooldown_seconds
                # Half-open after the cooldown: one more failure reopens immediately.
                self._failures = self.failure_threshold - 1


_MISSING = object()
