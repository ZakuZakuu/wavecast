"""Small in-memory, provider-independent accounting for a single run."""

import functools
import logging
from collections import deque
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, TypedDict, cast

from pydantic import BaseModel, Field

logger = logging.getLogger("wavecast.usage")

# Which unit of work (an episode id, or "proposal") the provider calls below belong to.
_usage_scope: ContextVar[str | None] = ContextVar("wavecast_usage_scope", default=None)

# The ledger is process-wide and in memory; keep it bounded on a long-running API.
DEFAULT_MAX_EVENTS = 4000


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
    provider: str
    operation: str
    request_id: str | None = None
    elapsed_ms: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
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
    input_tokens: int
    output_tokens: int
    usage_characters: int
    reasoning_tokens: int
    search_queries: int
    search_credits: float
    actual_cost_usd: float
    estimated_cost_usd: float


class UsageDiagnostics(TypedDict):
    usage: dict[str, object]
    usage_by_stage: dict[str, dict[str, object]]
    provider_events: list[dict[str, object]]


class UsageLedger:
    def __init__(self, max_events: int = DEFAULT_MAX_EVENTS) -> None:
        self._events: deque[UsageEvent] = deque(maxlen=max_events)

    @property
    def events(self) -> list[UsageEvent]:
        return list(self._events)

    def record(self, event: UsageEvent) -> None:
        self._events.append(event)
        # Counts, timings and cost only: never prompts, responses, URLs or user identifiers.
        logger.info(
            "provider_call provider=%s operation=%s stage=%s scope=%s ms=%d in=%s out=%s "
            "chars=%s queries=%s cost_usd=%s",
            event.provider,
            event.operation,
            event.metadata.get("stage") if isinstance(event.metadata.get("stage"), str) else None,
            event.scope,
            event.elapsed_ms,
            event.input_tokens,
            event.output_tokens,
            event.usage_characters,
            event.search_queries,
            event.actual_cost_usd if event.actual_cost_usd is not None else event.estimated_cost_usd,
        )

    def for_scope(self, scope: str) -> list[UsageEvent]:
        return [event for event in self._events if event.scope == scope]

    def totals(self) -> UsageTotals:
        return self._totals(self.events)

    def totals_for_stage(self, stage: str) -> UsageTotals:
        return self._totals([event for event in self.events if event.metadata.get("stage") == stage])

    @staticmethod
    def _totals(events: list[UsageEvent]) -> UsageTotals:
        return UsageTotals(
            event_count=len(events),
            input_tokens=sum(event.input_tokens or 0 for event in events),
            output_tokens=sum(event.output_tokens or 0 for event in events),
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
        )


def safe_usage_event(event: UsageEvent) -> dict[str, object]:
    """Return only bounded metadata suitable for a diagnostic report."""

    metadata = event.metadata

    def metadata_value(name: str) -> object:
        value = metadata.get(name)
        return value if value is None or isinstance(value, (bool, int, float, str)) else None

    stage = metadata.get("stage")
    return {
        "provider": event.provider,
        "operation": event.operation,
        "stage": stage if isinstance(stage, str) else None,
        "elapsed_ms": event.elapsed_ms,
        "input_tokens": event.input_tokens,
        "output_tokens": event.output_tokens,
        "usage_characters": event.usage_characters,
        "search_queries": event.search_queries,
        "search_credits": event.search_credits,
        "actual_cost_usd": event.actual_cost_usd,
        "estimated_cost_usd": event.estimated_cost_usd,
        "model": metadata_value("model"),
        "transport": metadata_value("transport"),
        "finish_reason": metadata_value("finish_reason"),
        "reasoning_tokens": metadata_value("reasoning_tokens"),
    }


def usage_diagnostics(ledger: UsageLedger, scope: str | None = None) -> UsageDiagnostics:
    """Summarise the ledger, or only the calls made for one ``scope`` (e.g. an episode)."""

    events = ledger.events if scope is None else ledger.for_scope(scope)
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
        "provider_events": [safe_usage_event(event) for event in events],
    }
