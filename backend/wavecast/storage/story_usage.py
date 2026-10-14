"""Persisting the story-usage ledger (one JSON document per episode, in object storage).

Updates are read-modify-write under a per-episode lock held by the store instance, which
serialises the writers inside one process.  Object storage has no compare-and-set, so two
processes writing the same episode could still lose an update; a database row with a version is
the follow-up (see ADR 0026).  Authoring one episode's narration is single-writer today.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable, Iterable

from pydantic import ValidationError

from wavecast.models.episode import MusicSegment, NarrationSegment, SegmentState
from wavecast.models.story_usage import Reservation, StoryUsageLedger, StoryUseState
from wavecast.providers.contracts import ObjectStorageProvider

_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")


class StoryUsageError(ValueError):
    """The stored ledger is damaged, unversioned or of an unknown version."""


def usage_key(episode_id: str) -> str:
    if not _SAFE_SEGMENT.fullmatch(episode_id):
        raise ValueError("episode id used in a storage key must be a plain token")
    return f"story-usage/{episode_id}.json"


class StoryUsageStore:
    def __init__(self, storage: ObjectStorageProvider) -> None:
        self._storage = storage
        self._locks: dict[str, asyncio.Lock] = {}

    async def load(self, episode_id: str) -> StoryUsageLedger:
        stored = await self._storage.get(usage_key(episode_id))
        if stored is None:
            return StoryUsageLedger.empty()
        content = getattr(stored, "content", None)
        if not isinstance(content, bytes):
            raise StoryUsageError("stored ledger has no readable content")
        try:
            payload = json.loads(content)
        except ValueError as error:
            raise StoryUsageError("stored ledger is damaged") from error
        if not isinstance(payload, dict) or "schema_version" not in payload:
            raise StoryUsageError("stored ledger does not declare a schema_version")
        if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
            raise StoryUsageError(f"unsupported ledger schema_version {payload['schema_version']!r}")
        try:
            return StoryUsageLedger.model_validate(payload)
        except ValidationError as error:
            raise StoryUsageError("stored ledger is damaged or inconsistent") from error

    async def _update[T](
        self, episode_id: str, change: Callable[[StoryUsageLedger], T]
    ) -> T:
        lock = self._locks.setdefault(episode_id, asyncio.Lock())
        async with lock:
            ledger = await self.load(episode_id)
            result = change(ledger)
            await self._storage.put(
                usage_key(episode_id),
                ledger.model_dump_json().encode("utf-8"),
                "application/json",
                {"schema_version": ledger.schema_version},
            )
            return result

    async def reserve(self, episode_id: str, story_id: str, block_id: str) -> Reservation:
        return await self._update(episode_id, lambda ledger: ledger.reserve(story_id, block_id))

    async def release(self, episode_id: str, story_id: str, block_id: str) -> bool:
        return await self._update(episode_id, lambda ledger: ledger.release(story_id, block_id))

    async def reconcile(
        self, episode_id: str, segments: Iterable[MusicSegment | NarrationSegment]
    ) -> StoryUsageLedger:
        """Bring the ledger in line with what happened to the episode's dialogue segments.

        A segment the listener has reached (committed or played) makes its story *told*; one
        that was skipped gives its reservation back.  Anything else is left as it is.
        """

        def apply(ledger: StoryUsageLedger) -> StoryUsageLedger:
            for segment in segments:
                block = segment.dialogue if isinstance(segment, NarrationSegment) else None
                if block is None or block.story_id is None:
                    continue
                if segment.state in (SegmentState.COMMITTED, SegmentState.PLAYED):
                    ledger.publish(block.story_id, block.block_id)
                elif segment.state is SegmentState.SKIPPED:
                    entry = ledger.entries.get(block.story_id)
                    if (
                        entry is not None
                        and entry.block_id == block.block_id
                        and entry.state is StoryUseState.RESERVED
                    ):
                        ledger.release(block.story_id, block.block_id)
            return ledger.model_copy(deep=True)

        return await self._update(episode_id, apply)

    async def release_orphans(self, episode_id: str, live_block_ids: Iterable[str]) -> list[str]:
        """Give back reservations whose passage never made it into the timeline.

        A crash between reserving a story and inserting its passage would otherwise hold the
        story for good.  Call this only when no authoring for the episode is in flight; told
        (published) stories are never touched.  Returns the stories released.
        """

        live = set(live_block_ids)

        def apply(ledger: StoryUsageLedger) -> list[str]:
            orphaned = [
                entry.story_id
                for entry in ledger.entries.values()
                if entry.state is StoryUseState.RESERVED and entry.block_id not in live
            ]
            for story_id in orphaned:
                del ledger.entries[story_id]
            return orphaned

        return await self._update(episode_id, apply)
