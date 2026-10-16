"""Small in-memory, provider-independent accounting for a single run."""

import asyncio
import functools
import logging
from collections import deque
from collections.abc import Awaitable, Callable, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, Protocol, TypedDict, cast
from uuid import uuid4

from pydantic import BaseModel, Field

logger = logging.getLogger("wavecast.usage")

# Which unit of work (an episode id, or "proposal") the provider calls below belong to.
_usage_scope: ContextVar[str | None] = ContextVar("wavecast_usage_scope", default=None)

# The ledger is process-wide and in memory; keep it bounded on a long-running API.
DEFAULT_MAX_EVENTS = 4000


# Whether the calls belong to a whole generation or to a text-only rewrite of a stored episode
# ("generation" / "replay"); unset when the caller does not say.
_usage_run_kind: ContextVar[str | None] = ContextVar("wavecast_usage_run_kind", default=None)


@contextmanager
def usage_run_kind(kind: str) -> Iterator[None]:
    """Label every provider call made inside the block, so reports can tell replays apart."""

    token = _usage_run_kind.set(kind)
    try:
        yield
    finally:
        _usage_run_kind.reset(token)


@contextmanager
def usage_scope(scope: str) -> Iterator[None]:
    """Attribute every provider call made inside the block to ``scope``."""

    token = _usage_scope.set(scope)
    try:
        yield
    finally:
        _usage_scope.reset(token)


def scoped_to_episode[F: Callable[..., Awaitable[Any]]](method: F) -> F:
    """Run an async method taking ``(self, episode, ...)`` inside ``usage_scope(episode.id)``."""

    @functools.wraps(method)
    async def wrapper(self: Any, episode: Any, *args: Any, **kwargs: Any) -> Any:
        with usage_scope(str(episode.id)):
            return await method(self, episode, *args, **kwargs)

    return cast(F, wrapper)


class UsageEvent(BaseModel):
    # Identifies this call across the in-memory ledger and its stored copy, so reading both
    # (after a restart, or while the copy is still being written) never counts one call twice.
    event_id: str = Field(default_factory=lambda: uuid4().hex)
    provider: str
    operation: str
    request_id: str | None = None
    elapsed_ms: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    # Prompt-cache split of ``input_tokens``.  ``None`` means the provider did not say, which is
    # not the same as zero: an unknown split is never counted as a miss or as a hit.
    cached_input_tokens: int | None = Field(default=None, ge=0)
    uncached_input_tokens: int | None = Field(default=None, ge=0)
    usage_characters: int | None = Field(default=None, ge=0)
    search_queries: int | None = Field(default=None, ge=0)
    search_credits: float | None = Field(default=None, ge=0)
    actual_cost_usd: float | None = Field(default=None, ge=0)
    estimated_cost_usd: float | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    scope: str | None = Field(default_factory=lambda: _usage_scope.get())
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class UsageTotals(BaseModel):
    event_count: int
    # Time spent waiting on providers (sum over calls, so calls that overlap add up), and
    # the single slowest call: enough to see which stage is slow without a tracing system.
    elapsed_ms: int
    slowest_ms: int
    input_tokens: int
    output_tokens: int
    # Only calls that reported a cache split count here; ``cache_reported_input_tokens`` is
    # their input, so the hit rate is cached / reported and unreported calls stay out of it.
    cached_input_tokens: int = 0
    uncached_input_tokens: int = 0
    cache_reported_input_tokens: int = 0
    cache_unreported_calls: int = 0
    usage_characters: int
    reasoning_tokens: int
    search_queries: int
    search_credits: float
    actual_cost_usd: float
    estimated_cost_usd: float
    # The USD totals above never include Ark: its cost is estimated in CNY and nothing is
    # converted.  These sum the CNY figures that providers put in event metadata.  The point
    # estimate counts only calls with one; low/high bracket calls priced by a range; calls with
    # a currency basis but no figure at all are counted, not treated as free.
    estimated_cost_cny: float = 0.0
    estimated_cost_cny_low: float = 0.0
    estimated_cost_cny_high: float = 0.0
    cost_unknown_calls: int = 0
    # Speech services bill audio, not text: the counts the service reported, summed over the
    # attempts that carried them (an attempt without a count adds nothing - it is not a zero).
    # ``usage_incomplete_calls`` counts attempts whose counts are partial or unknown.
    input_text_tokens: int = 0
    output_audio_tokens: int = 0
    usage_incomplete_calls: int = 0


class UsageDiagnostics(TypedDict):
    usage: dict[str, object]
    usage_by_stage: dict[str, dict[str, object]]
    provider_events: list[dict[str, object]]


class UsageSink(Protocol):
    """Where a ledger keeps its events beyond the process (see ``storage.usage_events``)."""

    async def append(self, scope: str, event: UsageEvent) -> None: ...


class UsageLedger:
    def __init__(self, max_events: int = DEFAULT_MAX_EVENTS) -> None:
        self._events: deque[UsageEvent] = deque(maxlen=max_events)
        self._sink: UsageSink | None = None
        self._pending: set[asyncio.Task[None]] = set()

    def attach_sink(self, sink: UsageSink) -> None:
        """Also keep every scoped event in ``sink``; a failing sink never affects a provider call."""
        self._sink = sink

    async def flush(self) -> None:
        """Wait until every event recorded so far has been handed to the sink."""
        while self._pending:
            await asyncio.gather(*list(self._pending), return_exceptions=True)

    @property
    def events(self) -> list[UsageEvent]:
        return list(self._events)

    def record(self, event: UsageEvent) -> None:
        kind = _usage_run_kind.get()
        if kind is not None and "run_kind" not in event.metadata:
            event.metadata["run_kind"] = kind
        self._events.append(event)
        self._persist(event)
        # Counts, timings and cost only: never prompts, responses, URLs or user identifiers.
        logger.info(
            "provider_call provider=%s operation=%s stage=%s scope=%s ms=%d in=%s out=%s "
            "cached=%s chars=%s queries=%s cost_usd=%s",
            event.provider,
            event.operation,
            event.metadata.get("stage") if isinstance(event.metadata.get("stage"), str) else None,
            event.scope,
            event.elapsed_ms,
            event.input_tokens,
            event.output_tokens,
            event.cached_input_tokens,
            event.usage_characters,
            event.search_queries,
            event.actual_cost_usd if event.actual_cost_usd is not None else event.estimated_cost_usd,
        )

    def _persist(self, event: UsageEvent) -> None:
        if self._sink is None or event.scope is None:
            return
        try:
            task = asyncio.get_running_loop().create_task(self._append(self._sink, event))
        except RuntimeError:  # no running loop: this event stays in memory only
            logger.warning("usage_event_not_persisted reason=no_running_loop")
            return
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    @staticmethod
    async def _append(sink: UsageSink, event: UsageEvent) -> None:
        try:
            await sink.append(event.scope or "", event)
        except Exception as error:  # noqa: BLE001 - accounting must never break a generation
            logger.warning("usage_event_not_persisted error_type=%s", type(error).__name__)

    def for_scope(self, scope: str) -> list[UsageEvent]:
        return [event for event in self._events if event.scope == scope]

    def totals(self) -> UsageTotals:
        return self._totals(self.events)

    def totals_for_stage(self, stage: str) -> UsageTotals:
        return self._totals([event for event in self.events if event.metadata.get("stage") == stage])

    @staticmethod
    def _totals(events: list[UsageEvent]) -> UsageTotals:
        reported = [event for event in events if event.cached_input_tokens is not None]
        return UsageTotals(
            event_count=len(events),
            elapsed_ms=sum(event.elapsed_ms for event in events),
            slowest_ms=max((event.elapsed_ms for event in events), default=0),
            input_tokens=sum(event.input_tokens or 0 for event in events),
            output_tokens=sum(event.output_tokens or 0 for event in events),
            cached_input_tokens=sum(event.cached_input_tokens or 0 for event in reported),
            uncached_input_tokens=sum(event.uncached_input_tokens or 0 for event in reported),
            cache_reported_input_tokens=sum(event.input_tokens or 0 for event in reported),
            cache_unreported_calls=sum(
                1
                for event in events
                if event.input_tokens is not None and event.cached_input_tokens is None
            ),
            usage_characters=sum(event.usage_characters or 0 for event in events),
            reasoning_tokens=sum(
                value
                for event in events
                if isinstance((value := event.metadata.get("reasoning_tokens")), int)
                and value >= 0
            ),
            search_queries=sum(event.search_queries or 0 for event in events),
            search_credits=sum(event.search_credits or 0 for event in events),
            actual_cost_usd=sum(event.actual_cost_usd or 0 for event in events),
            estimated_cost_usd=sum(event.estimated_cost_usd or 0 for event in events),
            estimated_cost_cny=sum(_cny(event, "estimated_cost_cny") or 0 for event in events),
            estimated_cost_cny_low=sum(_cny(event, "estimated_cost_cny_low") or 0 for event in events),
            estimated_cost_cny_high=sum(
                _cny(event, "estimated_cost_cny_high") or 0 for event in events
            ),
            cost_unknown_calls=sum(
                1
                for event in events
                if "cost_basis" in event.metadata and _cny(event, "estimated_cost_cny_low") is None
            ),
            input_text_tokens=sum(_count(event, "input_text_tokens") or 0 for event in events),
            output_audio_tokens=sum(_count(event, "output_audio_tokens") or 0 for event in events),
            usage_incomplete_calls=sum(
                1
                for event in events
                if event.metadata.get("usage_status") in ("partial", "unknown")
            ),
        )


def _cny(event: UsageEvent, name: str) -> float | None:
    value = event.metadata.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    return float(value)


def _count(event: UsageEvent, name: str) -> int | None:
    value = event.metadata.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


_CALL_OUTCOME_FIELDS = (
    "role",
    "outcome",
    "request_dispatched",
    "response_received",
    "usage_known",
    "http_status",
    "estimated_cost_cny",
    "estimated_cost_cny_low",
    "estimated_cost_cny_high",
    "cost_basis",
    "price_version",
    # Speech: the service's own counts (null = unknown), how complete they are, and how far the
    # attempt got.
    "input_text_tokens",
    "output_audio_tokens",
    "usage_status",
    "rounds_completed",
    "audio_seconds",
    "sent_characters",
    "failed_stage",
    # Search: how a request ended and what it brought back.
    "error_type",
    "result_count",
)


def safe_usage_event(event: UsageEvent) -> dict[str, object]:
    """Return only bounded metadata suitable for a diagnostic report."""

    metadata = event.metadata

    def metadata_value(name: str) -> object:
        value = metadata.get(name)
        return value if value is None or isinstance(value, (bool, int, float, str)) else None

    stage = metadata.get("stage")
    projected: dict[str, object] = {
        "provider": event.provider,
        "operation": event.operation,
        "stage": stage if isinstance(stage, str) else None,
        "elapsed_ms": event.elapsed_ms,
        "input_tokens": event.input_tokens,
        "output_tokens": event.output_tokens,
        "cached_input_tokens": event.cached_input_tokens,
        "uncached_input_tokens": event.uncached_input_tokens,
        "usage_characters": event.usage_characters,
        "search_queries": event.search_queries,
        "search_credits": event.search_credits,
        "actual_cost_usd": event.actual_cost_usd,
        "estimated_cost_usd": event.estimated_cost_usd,
        "model": metadata_value("model"),
        "transport": metadata_value("transport"),
        "response_model": metadata_value("response_model"),
        "run_kind": metadata_value("run_kind"),
        "finish_reason": metadata_value("finish_reason"),
        "reasoning_tokens": metadata_value("reasoning_tokens"),
    }
    # Providers that price in CNY and report how a call ended (Ark) add these.  Unknown stays
    # null; it is never reported as zero.  Other providers' events keep their exact shape.
    for name in _CALL_OUTCOME_FIELDS:
        if name in metadata:
            projected[name] = metadata_value(name)
    return projected


def usage_diagnostics(ledger: UsageLedger, scope: str | None = None) -> UsageDiagnostics:
    """Summarise the ledger, or only the calls made for one ``scope`` (e.g. an episode)."""

    return diagnostics_of(ledger.events if scope is None else ledger.for_scope(scope))


def diagnostics_of(events: list[UsageEvent], *, with_ids: bool = False) -> UsageDiagnostics:
    """``with_ids`` adds each event's id and time (the per-episode report needs them to show that a
    call is counted once); the projection every other caller sees keeps its exact shape."""

    stages: dict[str, dict[str, object]] = {}
    for event in events:
        stage = event.metadata.get("stage")
        if isinstance(stage, str) and stage and stage not in stages:
            stages[stage] = UsageLedger._totals(
                [item for item in events if item.metadata.get("stage") == stage]
            ).model_dump()
    return {
        "usage": UsageLedger._totals(events).model_dump(),
        "usage_by_stage": stages,
        "provider_events": [
            {
                **({"event_id": event.event_id, "recorded_at": event.recorded_at.isoformat()} if with_ids else {}),
                **safe_usage_event(event),
            }
            for event in events
        ],
    }


def merge_events(*groups: Iterable[UsageEvent]) -> list[UsageEvent]:
    """Every call once, in the order it happened: the same ``event_id`` seen twice is one call
    (the first group listed wins, so list the live ledger before its stored copy)."""

    seen: dict[str, UsageEvent] = {}
    for group in groups:
        for event in group:
            seen.setdefault(event.event_id, event)
    return sorted(seen.values(), key=lambda event: event.recorded_at)


def cost_summary(events: Iterable[UsageEvent]) -> dict[str, Any]:
    """Cost per currency, never mixed, with the calls whose cost is unknown listed apart.

    CNY: the estimates Ark and the speech service put in their events.  USD: what the search
    service reported as actually charged.  Search credits: Tavily's own unit.  A call with no
    figure in any of these (a failed request, a missing receipt) is *unknown*, not zero.
    """

    cny = usd = credits = 0.0
    cny_calls = usd_calls = credit_calls = 0
    unknown: list[dict[str, Any]] = []
    for event in events:
        known = False
        if (value := _cny(event, "estimated_cost_cny")) is not None:
            cny += value
            cny_calls += 1
            known = True
        if event.actual_cost_usd is not None:
            usd += event.actual_cost_usd
            usd_calls += 1
            known = True
        elif event.estimated_cost_usd is not None:
            usd += event.estimated_cost_usd
            usd_calls += 1
            known = True
        if event.search_credits is not None:
            credits += event.search_credits
            credit_calls += 1
            known = True
        if not known:
            stage = event.metadata.get("stage")
            unknown.append(
                {
                    "provider": event.provider,
                    "operation": event.operation,
                    "stage": stage if isinstance(stage, str) else None,
                    "outcome": event.metadata.get("outcome")
                    if isinstance(event.metadata.get("outcome"), str)
                    else None,
                }
            )
    return {
        "cny": {"estimated": round(cny, 6), "priced_calls": cny_calls},
        "usd": {"charged_or_estimated": round(usd, 6), "priced_calls": usd_calls},
        "search_credits": {"reported": credits, "calls": credit_calls},
        "unknown_calls": unknown,
        "note": "currencies are never converted; a call with no figure is listed as unknown, not counted as zero",
    }
