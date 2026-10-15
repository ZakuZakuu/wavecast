"""First-pass rate, repair-trigger rate, repair-success rate, and what the repair adds.

Offline.  The archived 2026-10-15 portrait run is ONE passage: it shows how the numbers are
read from a real run, and by itself proves nothing about how rare or how effective the repair is.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from wavecast.intelligence.dialogue_metrics import (
    MIN_SAMPLE_FOR_RATES,
    DialogueMetrics,
    LedgerMark,
    PassageAttempt,
    repair_cost_cny,
    sentence_count,
    sentences_lost,
)
from wavecast.intelligence.dialogue_pipeline import DialogueStatus
from wavecast.providers.usage import UsageEvent, UsageLedger, usage_scope

from tests.dialogue_fixtures import clean_draft, draft_with_two_problems, good_repair
from tests.test_dialogue_pipeline import SLOT, build, material

FIXTURES = Path(__file__).parent / "fixtures" / "dialogue_portrait_20261015"


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# --- counting ---------------------------------------------------------------------------------


def test_sentences_are_counted_and_only_removals_count_as_loss() -> None:
    assert sentence_count("甲乙。丙丁！戊？") == 3
    assert sentences_lost("甲乙。丙丁。", "甲乙。") == 1
    assert sentences_lost("甲乙。", "甲乙。丙丁。") == 0  # adding is not a loss
    assert sentences_lost("甲乙。丙丁。", "甲乙，丙丁。") == 1  # merged into one sentence: counted, cautiously


def attempts(**counts: int) -> list[PassageAttempt]:
    out: list[PassageAttempt] = []
    out += [PassageAttempt(reached_first_check=True, first_check_passed=True)] * counts.get("clean", 0)
    out += [
        PassageAttempt(True, repair_triggered=True, repair_succeeded=True, extra_seconds=10.0, extra_cost_cny=0.02,
                       information_loss_sentences=1)
    ] * counts.get("fixed", 0)  # fmt: skip
    out += [PassageAttempt(True, repair_triggered=True, extra_seconds=14.0, extra_cost_cny=0.03)] * counts.get("failed", 0)
    out += [PassageAttempt(True)] * counts.get("no_repair", 0)  # refused, no repair tried
    out += [PassageAttempt(False, rejected_before_check="too_long")] * counts.get("too_long", 0)
    return out


def summary(**counts: int) -> dict[str, Any]:
    metrics = DialogueMetrics()
    for attempt in attempts(**counts):
        metrics.add(attempt)
    return metrics.summary()


def test_each_rate_has_its_own_denominator() -> None:
    result = summary(clean=6, fixed=2, failed=1, no_repair=1, too_long=3)

    assert result["passages"] == 13 and result["reached_first_check"] == 10
    assert result["rejected_before_check"] == {"too_long": 3}  # in none of the rates
    assert result["first_pass"] == {"count": 6, "of": 10, "rate": 0.6}
    assert result["repair_triggered"] == {"count": 3, "of": 10, "rate": 0.3}
    assert result["repair_succeeded"] == {"count": 2, "of": 3, "rate": 0.6667}
    assert result["first_check_not_passed_without_repair"] == 1


def test_extra_cost_time_and_loss_are_those_of_the_repairs_only() -> None:
    result = summary(clean=6, fixed=2, failed=1)

    assert result["extra_cost_cny"] == {"total": 0.07, "mean_per_repair": 0.023333, "repairs_with_known_cost": 3, "repairs": 3}
    assert result["extra_seconds"] == {"total": 34.0, "mean_per_repair": 11.33}
    assert result["information_loss_sentences"] == 2 and result["repairs_with_information_loss"] == 2


def test_nothing_is_invented_when_there_is_nothing_to_divide() -> None:
    empty = summary()
    assert empty["first_pass"]["rate"] is None and empty["repair_succeeded"]["rate"] is None
    assert empty["extra_cost_cny"]["total"] is None and empty["extra_seconds"]["total"] is None

    no_repairs = summary(clean=3)
    assert no_repairs["repair_succeeded"] == {"count": 0, "of": 0, "rate": None}
    unknown_cost = DialogueMetrics([PassageAttempt(True, repair_triggered=True, repair_succeeded=True, extra_cost_cny=None)])
    assert unknown_cost.summary()["extra_cost_cny"]["total"] is None  # unknown, not zero


def test_rates_are_only_called_established_on_enough_passages() -> None:
    assert summary(clean=MIN_SAMPLE_FOR_RATES - 1)["rates_established"] is False
    assert summary(clean=MIN_SAMPLE_FOR_RATES)["rates_established"] is True
    assert summary(too_long=100)["rates_established"] is False  # refused passages are not evidence


# --- price of the repair ------------------------------------------------------------------------


def event(stage: str, cost: float | None, scope: str | None = "ep") -> UsageEvent:
    metadata: dict[str, Any] = {"stage": stage}
    if cost is not None:
        metadata["estimated_cost_cny"] = cost
    return UsageEvent(provider="ark", operation="structured", elapsed_ms=1, scope=scope, metadata=metadata)


def test_the_repair_price_is_the_repair_call_and_the_recheck_of_that_passage() -> None:
    events = [event("dialogue_writer", 0.01), event("dialogue_fact_check", 0.02), event("dialogue_repair", 0.002),
              event("dialogue_fact_check", 0.023), event("dialogue_repair", 9.0, scope="other")]  # fmt: skip
    # the first check belongs to the passage itself; only calls after the mark are the repair's
    assert repair_cost_cny(events[2:], "ep") == pytest.approx(0.025)
    assert repair_cost_cny(events[2:4], None) is None  # no scope match


def test_a_repair_with_one_unpriced_call_has_no_price_rather_than_a_partial_one() -> None:
    assert repair_cost_cny([event("dialogue_repair", 0.002), event("dialogue_fact_check", None)], "ep") is None
    assert repair_cost_cny([], "ep") is None


def test_the_mark_sees_only_events_added_after_it_and_only_for_the_current_scope() -> None:
    ledger = UsageLedger()
    ledger.record(event("dialogue_fact_check", 0.5, scope="ep"))
    mark = LedgerMark(ledger)
    with usage_scope("ep"):
        ledger.record(event("dialogue_repair", 0.002, scope="ep"))
        ledger.record(event("dialogue_fact_check", 0.023, scope="ep"))
        ledger.record(event("dialogue_repair", 7.0, scope="someone-else"))
        assert mark.repair_cost_cny() == pytest.approx(0.025)
    assert LedgerMark(None).repair_cost_cny() is None


# --- through the pipeline -----------------------------------------------------------------------


def run_with_metrics(draft: Any, **kwargs: Any) -> tuple[Any, DialogueMetrics]:
    pipeline, _, _ = build(draft, **kwargs)
    pipeline._metrics = metrics = DialogueMetrics()  # the same wiring the stack does
    return asyncio.run(pipeline.produce(material(), SLOT)), metrics


def test_a_clean_passage_counts_as_a_first_pass() -> None:
    outcome, metrics = run_with_metrics(clean_draft())
    assert outcome.status is DialogueStatus.READY
    result = metrics.summary()
    assert result["first_pass"]["count"] == 1 and result["repair_triggered"]["count"] == 0


def test_a_repaired_passage_counts_as_triggered_and_succeeded_with_its_time_and_loss() -> None:
    outcome, metrics = run_with_metrics(draft_with_two_problems(), repair=good_repair())
    assert outcome.status is DialogueStatus.REPAIRED
    result = metrics.summary()
    assert result["first_pass"]["count"] == 0 and result["repair_triggered"]["count"] == 1
    assert result["repair_succeeded"]["count"] == 1
    assert result["extra_seconds"]["total"] is not None and result["extra_seconds"]["total"] >= 0
    assert result["extra_cost_cny"]["total"] is None  # this pipeline had no priced ledger: unknown
    assert result["information_loss_sentences"] == 0  # the fixture repair rewords, it does not delete


def test_a_passage_the_writer_made_too_long_is_counted_apart_from_the_rates() -> None:
    from wavecast.intelligence.dialogue_budget import DialogueStationBudget

    pipeline, _, _ = build(clean_draft())
    pipeline._metrics = metrics = DialogueMetrics()
    import wavecast.intelligence.dialogue_pipeline as module

    original = module.dialogue_budget_for
    module.dialogue_budget_for = lambda station: DialogueStationBudget(1, 2, 5, 0.5)  # type: ignore[assignment]
    try:
        outcome = asyncio.run(pipeline.produce(material(), SLOT))
    finally:
        module.dialogue_budget_for = original
    assert outcome.reason == "too_long"
    result = metrics.summary()
    assert result["rejected_before_check"] == {"too_long": 1} and result["reached_first_check"] == 0


# --- the archived run ---------------------------------------------------------------------------


def archived_attempts() -> list[PassageAttempt]:
    """The two passages the live acceptance made, read from the archived files."""

    casual = load("casual-attempt.summary.safe.json")
    first, second = load("run1-first-attempt.summary.safe.json"), load("run2-local-repair.summary.safe.json")
    check1, check2 = load("check.result.json"), load("check.after-repair.json")
    repaired = load("candidate.repaired.unchecked.json")["turns"]

    events = [
        UsageEvent(provider=e["provider"], operation=e["operation"], elapsed_ms=e["elapsed_ms"], scope="run",
                   metadata={"stage": e["stage"], "estimated_cost_cny": e.get("estimated_cost_cny")})
        for e in second["increment"]["provider_events"]
        if e["provider"] == "ark"
    ]  # fmt: skip
    loss = sum(sentences_lost(t["before"], t["text"]) for t in repaired if t["changed"])
    return [
        # the casual-budget draft was refused before any check
        PassageAttempt(False, rejected_before_check=casual["reason"]),
        PassageAttempt(
            reached_first_check=bool(first["stage_seconds"].get("fact_check")),
            first_check_passed=check1["passed"],
            repair_triggered=bool(second["stage_seconds"].get("repair")),
            repair_succeeded=check2["passed"] and second["status"] == "completed",
            extra_seconds=second["stage_seconds"]["repair"] + second["stage_seconds"]["recheck"],
            extra_cost_cny=repair_cost_cny(events, "run"),
            information_loss_sentences=loss,
        ),
    ]


def test_the_archived_run_reads_as_one_repaired_passage_and_one_refused_draft() -> None:
    metrics = DialogueMetrics(archived_attempts())
    result = metrics.summary()

    assert result["rejected_before_check"] == {"draft_exceeds_short_probe_budget": 1}
    assert result["first_pass"] == {"count": 0, "of": 1, "rate": 0.0}
    assert result["repair_triggered"] == {"count": 1, "of": 1, "rate": 1.0}
    assert result["repair_succeeded"] == {"count": 1, "of": 1, "rate": 1.0}
    assert result["extra_seconds"]["total"] == pytest.approx(13.97)
    assert result["extra_cost_cny"]["total"] == pytest.approx(0.0251368, abs=1e-6)  # Lite 0.0017 + Pro 0.0235
    assert result["information_loss_sentences"] == 1  # turn 5 lost a whole sentence; recorded, not redone
    # one passage is not evidence that the repair is rare or that it works
    assert result["rates_established"] is False and result["reached_first_check"] == 1


# --- the archive itself ---------------------------------------------------------------------------


def test_the_archive_is_intact_and_holds_no_credentials() -> None:
    manifest = load("MANIFEST.json")
    assert manifest["acceptance_status"] == "人物志单段经过一次局部修复后通过，用户试听认可"
    for name, digest in manifest["files"].items():
        assert hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest() == digest, name
    assert manifest["information_loss"]["recorded_not_redone"] is True
    assert manifest["audio_attachment"]["kept_outside_the_repository"] is True
    for path in FIXTURES.iterdir():
        text = path.read_text(encoding="utf-8").lower()
        assert not any(marker in text for marker in ("api_key", "bearer ", "x-api-key", "access_token")), path.name


def test_the_archived_repair_changed_only_the_flagged_turns() -> None:
    before, after = load("candidate.unchecked.json")["turns"], load("candidate.repaired.unchecked.json")
    flagged = sorted({issue["turn"] for issue in load("check.result.json")["issues"]})
    assert after["changed_turns"] == flagged == [5, 7]
    for index, turn in enumerate(after["turns"]):
        assert turn["speaker"] == before[index]["speaker"]
        assert (turn["text"] != before[index]["text"]) == (index in flagged)
