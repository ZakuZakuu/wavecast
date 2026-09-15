"""Small monotonic latency traces for progressive generation."""

from dataclasses import dataclass, field
from time import monotonic_ns
from typing import Any


@dataclass(frozen=True)
class TraceEvent:
    name: str
    monotonic_timestamp_ms: int
    elapsed_from_start_ms: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class GenerationTrace:
    request_id: str
    _started_at_ns: int = field(default_factory=monotonic_ns, repr=False)
    events: list[TraceEvent] = field(default_factory=list)

    def mark(self, name: str, **metadata: Any) -> TraceEvent:
        now_ns = monotonic_ns()
        event = TraceEvent(
            name=name,
            monotonic_timestamp_ms=now_ns // 1_000_000,
            elapsed_from_start_ms=(now_ns - self._started_at_ns) // 1_000_000,
            metadata=metadata,
        )
        self.events.append(event)
        return event

    @property
    def time_to_first_script_ms(self) -> int | None:
        for event in self.events:
            if event.name == "first_script_ready":
                return event.elapsed_from_start_ms
        return None

    @property
    def fallback_used(self) -> bool:
        return any(event.name == "fallback_used" for event in self.events)
