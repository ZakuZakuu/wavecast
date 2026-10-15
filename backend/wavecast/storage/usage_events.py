"""Provider usage events kept beyond the process (one JSON document per scope, usually an episode).

The ledger in ``providers.usage`` is in memory and bounded; this keeps the same events, one
document per episode, in object storage, so the per-episode usage report still answers after a
restart.  Updates are read-modify-write under a per-scope lock held by the store instance (the
same trade-off as ``story_usage``: one writer process per episode).  Events carry counts,
timings and cost only - never prompts, responses, URLs or user identifiers.
"""

from __future__ import annotations

import asyncio
import json
import re

from pydantic import ValidationError

from wavecast.providers.contracts import ObjectStorageProvider
from wavecast.providers.usage import UsageEvent

_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
MAX_EVENTS_PER_SCOPE = 1000
SCHEMA_VERSION = 1


class UsageEventsError(ValueError):
    """The stored events are damaged or of an unknown version."""


def usage_events_key(scope: str) -> str:
    if not _SAFE_SEGMENT.fullmatch(scope):
        raise ValueError("scope used in a storage key must be a plain token")
    return f"usage-events/{scope}.json"


class UsageEventStore:
    def __init__(self, storage: ObjectStorageProvider) -> None:
        self._storage = storage
        self._locks: dict[str, asyncio.Lock] = {}

    async def load(self, scope: str) -> list[UsageEvent]:
        stored = await self._storage.get(usage_events_key(scope))
        if stored is None:
            return []
        content = getattr(stored, "content", None)
        if not isinstance(content, bytes):
            raise UsageEventsError("stored usage has no readable content")
        try:
            payload = json.loads(content)
        except ValueError as error:
            raise UsageEventsError("stored usage is damaged") from error
        if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
            raise UsageEventsError("stored usage has an unknown or missing schema_version")
        try:
            return [UsageEvent.model_validate(item) for item in payload.get("events", [])]
        except ValidationError as error:
            raise UsageEventsError("stored usage is damaged or inconsistent") from error

    async def append(self, scope: str, event: UsageEvent) -> None:
        key = usage_events_key(scope)
        async with self._locks.setdefault(scope, asyncio.Lock()):
            events = await self.load(scope)
            if any(item.event_id == event.event_id for item in events):
                return  # the same call, written twice
            events.append(event)
            document = {
                "schema_version": SCHEMA_VERSION,
                "events": [item.model_dump(mode="json") for item in events[-MAX_EVENTS_PER_SCOPE:]],
            }
            await self._storage.put(key, json.dumps(document).encode(), "application/json")
