"""Per-station budgets and frequency for two-host passages; the one-voice defaults stay as they are."""

from __future__ import annotations

import pytest
from wavecast.intelligence import voice
from wavecast.intelligence.dialogue_budget import (
    DIALOGUE_BUDGETS,
    DIALOGUE_CHARS_PER_SECOND,
    dialogue_budget_for,
    estimate_dialogue_seconds,
    story_slot_ids,
)
from wavecast.stations import StationId


def test_every_station_has_an_entry_and_night_stays_quiet() -> None:
    assert set(DIALOGUE_BUDGETS) == set(StationId)
    assert dialogue_budget_for(StationId.NIGHT) is None


def test_stations_keep_distinct_lengths_and_densities() -> None:
    budgets = {s: b for s, b in DIALOGUE_BUDGETS.items() if b is not None}

    for budget in budgets.values():
        assert 0 < budget.target_min_seconds < budget.target_max_seconds < budget.hard_max_seconds
        assert 0 < budget.slot_share < 1
    ordered = [StationId.CASUAL, StationId.CRATE, StationId.PORTRAIT, StationId.LINEAGE]
    maxima = [budgets[s].target_max_seconds for s in ordered]
    assert maxima == sorted(maxima) and len(set(maxima)) == 4  # 随便听 shortest, 来龙去脉 longest
    assert budgets[StationId.CASUAL].slot_share < budgets[StationId.PORTRAIT].slot_share


def test_target_characters_follow_the_measured_speaking_rate() -> None:
    budget = dialogue_budget_for(StationId.PORTRAIT)
    assert budget is not None

    low, high = budget.target_characters

    assert (low, high) == (int(50 * DIALOGUE_CHARS_PER_SECOND), int(90 * DIALOGUE_CHARS_PER_SECOND))
    # The accepted samples: 533 characters ≈ 87 s and 167 characters ≈ 28 s.
    assert abs(estimate_dialogue_seconds(533) - 87) <= 3
    assert abs(estimate_dialogue_seconds(167) - 28) <= 1
    assert estimate_dialogue_seconds(0) == 1 and estimate_dialogue_seconds(10**6) == 300


def test_selection_never_exceeds_the_share_and_may_pick_nothing() -> None:
    slots = [f"slot-{i}" for i in range(12)]

    for station, budget in DIALOGUE_BUDGETS.items():
        chosen = story_slot_ids(station, slots, "seed")
        assert len(chosen) <= (int(12 * budget.slot_share) if budget else 0)
        assert chosen == [s for s in slots if s in chosen]  # original order
    assert story_slot_ids(StationId.CASUAL, slots[:3], "seed") == []  # not every programme gets one
    assert story_slot_ids(StationId.PORTRAIT, [], "seed") == []
    assert story_slot_ids(StationId.NIGHT, slots, "seed") == []


def test_selection_is_deterministic_for_a_seed_and_varies_with_it() -> None:
    slots = [f"slot-{i}" for i in range(20)]

    first = story_slot_ids(StationId.LINEAGE, slots, "programme-a")

    assert first == story_slot_ids(StationId.LINEAGE, slots, "programme-a")
    assert any(story_slot_ids(StationId.LINEAGE, slots, f"p{n}") != first for n in range(8))


def test_nothing_enforces_a_minimum_length() -> None:
    # The lower target is only ever told to the Writer: the budget has no minimum field.
    fields = set(DIALOGUE_BUDGETS[StationId.PORTRAIT].__dataclass_fields__)  # type: ignore[union-attr]

    assert fields == {"target_min_seconds", "target_max_seconds", "hard_max_seconds", "slot_share"}


def test_the_one_voice_defaults_are_untouched() -> None:
    assert voice.MAX_SECONDS == {
        StationId.CASUAL: 15,
        StationId.CRATE: 20,
        StationId.PORTRAIT: 30,
        StationId.LINEAGE: 30,
        StationId.NIGHT: 8,
    }
    assert voice.MIN_FILL[StationId.CASUAL] == pytest.approx(0.45)
    assert voice.MIN_FILL[StationId.NIGHT] == 0.0
    assert voice.window_for(StationId.PORTRAIT, 100) == 30  # still capped at the one-voice limit
