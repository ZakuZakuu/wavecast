"""How often a researched passage needs its repair, and what the repair costs.

Four numbers are kept apart on purpose, each with its own denominator and never summed into a
single "quality" figure:

* **first-pass rate**   - passages whose first fact check was clean / passages that reached it;
* **repair-trigger rate** - passages the first check sent to repair / passages that reached it;
* **repair-success rate** - repaired passages that then passed / passages sent to repair;
* **extra cost and time** - what the repair and its re-check added (cost only where the
  provider reported a price; unknown is ``None``, never zero).

Passages the Writer produced but that were refused before any check (too long, invalid) are
counted by reason and are in none of the rates.  A repair that leaves a turn with fewer
sentences than before is counted as *information loss* - the repair kept the check happy by
removing something it had no reason to remove.

The summary says how many passages it rests on.  Below ``MIN_SAMPLE_FOR_RATES`` it still
reports the counts but marks the rates as not established: a handful of passages cannot show
that the repair is rare, or that it works.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from wavecast.providers.usage import UsageEvent, UsageLedger, current_usage_scope

MIN_SAMPLE_FOR_RATES = 30
_SENTENCE = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]*")
REPAIR_STAGES = ("dialogue_repair", "dialogue_fact_check")


def sentence_count(text: str) -> int:
    return len([piece for piece in _SENTENCE.findall(text) if piece.strip(" 。！？!?；;")])


def sentences_lost(before: str, after: str) -> int:
    """How many sentences a rewrite removed (never negative: adding one is not a loss)."""
    return max(0, sentence_count(before) - sentence_count(after))


@dataclass(frozen=True)
class PassageAttempt:
    reached_first_check: bool
    first_check_passed: bool = False
    repair_triggered: bool = False
    repair_succeeded: bool = False
    rejected_before_check: str | None = None
    # Interrupted before a result: its repair cost is real and counted, but it is no outcome and
    # stays out of every rate.
    cancelled: bool = False
    extra_seconds: float | None = None
    extra_cost_cny: float | None = None
    information_loss_sentences: int = 0


def repair_cost_cny(events: Iterable[UsageEvent], scope: str | None) -> float | None:
    """The price of the repair and the re-check among ``events`` (already limited to one passage).

    ``None`` when any of those calls has no reported price: a partial sum would pass for the cost.
    """

    chosen = [
        event
        for event in events
        if event.scope == scope and event.metadata.get("stage") in REPAIR_STAGES
    ]
    if not chosen:
        return None
    prices = [event.metadata.get("estimated_cost_cny") for event in chosen]
    if any(isinstance(p, bool) or not isinstance(p, (int, float)) for p in prices):
        return None
    return float(sum(prices))  # type: ignore[arg-type]


class LedgerMark:
    """Remembers which provider events existed, to price only what a later step added."""

    def __init__(self, ledger: UsageLedger | None) -> None:
        self._ledger = ledger
        self._seen = {id(event) for event in ledger.events} if ledger is not None else set()

    def added(self) -> list[UsageEvent]:
        if self._ledger is None:
            return []
        return [event for event in self._ledger.events if id(event) not in self._seen]

    def repair_cost_cny(self) -> float | None:
        return repair_cost_cny(self.added(), current_usage_scope())


@dataclass
class DialogueMetrics:
    attempts: list[PassageAttempt] = field(default_factory=list)

    def add(self, attempt: PassageAttempt) -> None:
        self.attempts.append(attempt)

    def summary(self) -> dict[str, Any]:
        finished = [a for a in self.attempts if not a.cancelled]
        reached = [a for a in finished if a.reached_first_check]
        repaired = [a for a in reached if a.repair_triggered]
        passed_first = sum(a.first_check_passed for a in reached)
        succeeded = sum(a.repair_succeeded for a in repaired)
        # What repairs cost counts every repair that started, whether or not it finished.
        started = [a for a in self.attempts if a.repair_triggered]
        costs = [a.extra_cost_cny for a in started if a.extra_cost_cny is not None]
        times = [a.extra_seconds for a in started if a.extra_seconds is not None]
        rejected: dict[str, int] = {}
        for attempt in finished:
            if attempt.rejected_before_check:
                rejected[attempt.rejected_before_check] = rejected.get(attempt.rejected_before_check, 0) + 1

        def rate(numerator: int, denominator: int) -> dict[str, Any]:
            return {
                "count": numerator,
                "of": denominator,
                "rate": round(numerator / denominator, 4) if denominator else None,
            }

        return {
            "passages": len(self.attempts),
            "reached_first_check": len(reached),
            "rejected_before_check": rejected,
            "first_pass": rate(passed_first, len(reached)),
            "repair_triggered": rate(len(repaired), len(reached)),
            # Not passed, and no repair tried (checker unavailable, too many turns flagged).
            "first_check_not_passed_without_repair": sum(
                not a.first_check_passed and not a.repair_triggered for a in reached
            ),
            "repair_succeeded": rate(succeeded, len(repaired)),
            "extra_cost_cny": {
                "total": round(sum(costs), 6) if costs else None,
                "mean_per_repair": round(sum(costs) / len(costs), 6) if costs else None,
                "repairs_with_known_cost": len(costs),
                "repairs": len(started),
            },
            "extra_seconds": {
                "total": round(sum(times), 2) if times else None,
                "mean_per_repair": round(sum(times) / len(times), 2) if times else None,
                "repairs_with_known_time": len(times),
            },
            "cancelled": len(self.attempts) - len(finished),
            "information_loss_sentences": sum(a.information_loss_sentences for a in started),
            "repairs_with_information_loss": sum(a.information_loss_sentences > 0 for a in started),
            "rates_established": len(reached) >= MIN_SAMPLE_FOR_RATES,
            "minimum_passages_for_rates": MIN_SAMPLE_FOR_RATES,
        }
