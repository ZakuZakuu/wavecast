"""Which shared stories a programme has already told, so none is told twice.

A story is *reserved* by one passage while that passage is being made or waits for its place,
*published* once the passage has reached the listener (it is then told, for good), and goes back
to being available if the passage is cancelled, skipped or fails before then.  Absence means
available.  Only one passage can hold a story at a time.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StoryUseState(StrEnum):
    RESERVED = "reserved"
    PUBLISHED = "published"


class Reservation(StrEnum):
    """What asking for a story came to."""

    ACQUIRED = "acquired"  # it was free; this passage holds it now
    HELD = "held"  # this same passage already holds it and is still being made
    TOLD = "told"  # this same passage was already published: the story is told
    TAKEN = "taken"  # another passage holds it or has told it


class StoryUseEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    story_id: str = Field(min_length=1, max_length=80)
    state: StoryUseState
    block_id: str = Field(min_length=1, max_length=120)


class StoryUsageLedger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Required on purpose: a ledger that does not say its version is not assumed to be version 1.
    schema_version: Literal[1]
    entries: dict[str, StoryUseEntry] = Field(default_factory=dict)

    @classmethod
    def empty(cls) -> StoryUsageLedger:
        return cls(schema_version=1)

    def state_of(self, story_id: str) -> StoryUseState | None:
        entry = self.entries.get(story_id)
        return entry.state if entry else None

    def reserve(self, story_id: str, block_id: str) -> Reservation:
        """Ask for the story on behalf of ``block_id``.

        Asking again with the same passage never starts a second telling: it reports that the
        passage is still being made (``HELD``) or already published (``TOLD``).
        """
        entry = self.entries.get(story_id)
        if entry is None:
            self.entries[story_id] = StoryUseEntry(
                story_id=story_id, state=StoryUseState.RESERVED, block_id=block_id
            )
            return Reservation.ACQUIRED
        if entry.block_id != block_id:
            return Reservation.TAKEN
        return Reservation.HELD if entry.state is StoryUseState.RESERVED else Reservation.TOLD

    def publish(self, story_id: str, block_id: str) -> None:
        """The passage reached the listener: the story is told.  Idempotent."""
        entry = self.entries.get(story_id)
        if entry is not None and entry.block_id != block_id:
            raise ValueError(f"story {story_id} belongs to another passage")
        self.entries[story_id] = StoryUseEntry(
            story_id=story_id, state=StoryUseState.PUBLISHED, block_id=block_id
        )

    def release(self, story_id: str, block_id: str) -> bool:
        """Give up a reservation (cancelled, skipped, failed).  A told story cannot be released."""
        entry = self.entries.get(story_id)
        if entry is None or entry.block_id != block_id:
            return False
        if entry.state is StoryUseState.PUBLISHED:
            raise ValueError(f"story {story_id} was already told and cannot be released")
        del self.entries[story_id]
        return True
