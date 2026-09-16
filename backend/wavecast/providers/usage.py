"""Small in-memory, provider-independent accounting for a single run."""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


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


class UsageLedger:
    def __init__(self) -> None:
        self.events: list[UsageEvent] = []

    def record(self, event: UsageEvent) -> None:
        self.events.append(event)

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
