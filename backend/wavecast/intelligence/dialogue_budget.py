"""Spoken-time targets and frequency for two-host passages, per station.

These are separate from the one-voice caps in ``voice.py``, which stay as they are: a passage of
researched talk is a different thing from a track introduction.  The numbers are *soft starting
points* (from the integration design), not accepted product parameters:

* the target range is told to the Writer; it is never a minimum.  A short passage that is
  well supported is fine, and nothing pads a passage to reach a length;
* ``hard_max_seconds`` is the only enforced bound, so a runaway draft does not reach the speaker;
* ``slot_share`` is the largest share of a programme's slots that may carry a story passage.
  No slot has to: not every song gets a host, and the share can select none.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from dataclasses import dataclass

from wavecast.stations import StationId

# Measured on the accepted samples: 533 characters took 87.1 s, 167 characters 28.5 s.
DIALOGUE_CHARS_PER_SECOND = 6.0


@dataclass(frozen=True)
class DialogueStationBudget:
    target_min_seconds: int
    target_max_seconds: int
    hard_max_seconds: int
    slot_share: float

    @property
    def target_characters(self) -> tuple[int, int]:
        return (
            int(self.target_min_seconds * DIALOGUE_CHARS_PER_SECOND),
            int(self.target_max_seconds * DIALOGUE_CHARS_PER_SECOND),
        )


# ``None``: the station has no researched two-host passages (night stays quiet).
DIALOGUE_BUDGETS: dict[StationId, DialogueStationBudget | None] = {
    StationId.CASUAL: DialogueStationBudget(25, 45, 60, 0.25),
    StationId.CRATE: DialogueStationBudget(40, 65, 85, 0.34),
    StationId.PORTRAIT: DialogueStationBudget(50, 90, 115, 0.5),
    StationId.LINEAGE: DialogueStationBudget(70, 120, 150, 0.5),
    StationId.NIGHT: None,
}


def dialogue_budget_for(station: StationId) -> DialogueStationBudget | None:
    return DIALOGUE_BUDGETS[station]


def estimate_dialogue_seconds(characters: int) -> int:
    """Spoken length of ``characters`` of dialogue, rounded up, within a block's 1..300 s."""
    return max(1, min(300, math.ceil(characters / DIALOGUE_CHARS_PER_SECOND)))


def story_slot_ids(station: StationId, slot_ids: Sequence[str], seed: str) -> list[str]:
    """The slots that may carry a story passage: at most ``slot_share`` of them, possibly none.

    Deterministic for a seed (so a resumed programme picks the same ones), spread by hashing
    rather than by position, and returned in the original order.
    """

    budget = DIALOGUE_BUDGETS[station]
    if budget is None or not slot_ids:
        return []
    count = int(len(slot_ids) * budget.slot_share)
    ranked = sorted(
        slot_ids, key=lambda slot: hashlib.sha256(f"{seed}:{slot}".encode()).hexdigest()
    )
    chosen = set(ranked[:count])
    return [slot for slot in slot_ids if slot in chosen]
