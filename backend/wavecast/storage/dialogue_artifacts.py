"""Where a fact-checked two-host passage is saved, and how it is read back.

A checked passage is saved as one versioned JSON document in object storage, beside (not inside)
the playable episode: ``NarrationSegment`` cannot carry a dialogue yet (ADR 0024), and this
record does not change that.  It holds what a later stage needs to voice the passage without
writing or checking it again: the block (turns, speakers, fact references, block and slot ids),
the material snapshot the references resolve against, and the outcome of the check.  Reading it
back re-validates the whole document, including that every cited fact exists in the snapshot, so
a damaged or hand-edited record is refused instead of being voiced.

Not covered here: a database table, linking the record to an episode's segments, and resuming a
programme from it.  Those belong to the batch that lets a dialogue enter the timeline.
"""

from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from wavecast.models.dialogue import DialogueAudioSnapshot, DialogueBlock, DialogueIssue
from wavecast.models.story_material import StoryMaterial
from wavecast.providers.contracts import ObjectStorageProvider
from wavecast.stations import StationId

ARTIFACT_PREFIX = "dialogue-artifacts"
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")


class DialogueArtifactError(ValueError):
    """The saved passage is missing its version, damaged, or no longer consistent."""


class CheckedDialogueRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Required on purpose: a record that does not say its version is not assumed to be version 1.
    schema_version: Literal[1]
    station: StationId
    status: Literal["ready", "repaired"]
    block: DialogueBlock
    material: StoryMaterial
    repaired_turns: list[int]
    # What the first check found, kept for inspection when a repair changed the passage.
    first_check_issues: list[DialogueIssue]
    calls_used: int
    model_checked: bool

    @model_validator(mode="after")
    def _references_resolve(self) -> CheckedDialogueRecord:
        unknown = set(self.block.fact_refs) - set(self.material.fact_ids)
        if unknown:
            raise ValueError(f"block cites facts missing from the material: {sorted(unknown)[:5]}")
        if any(not 0 <= turn < len(self.block.turns) for turn in self.repaired_turns):
            raise ValueError("repaired_turns points outside the block")
        return self


def audio_snapshot_key(episode_id: str, block_id: str) -> str:
    return artifact_key(episode_id, block_id).removesuffix(".json") + ".audio.json"


def artifact_key(episode_id: str, block_id: str) -> str:
    for part in (episode_id, block_id):
        if not _SAFE_SEGMENT.fullmatch(part):
            raise ValueError("episode and block ids used in a storage key must be plain tokens")
    return f"{ARTIFACT_PREFIX}/{episode_id}/{block_id}.json"


class DialogueArtifactStore:
    def __init__(self, storage: ObjectStorageProvider) -> None:
        self._storage = storage

    async def save(self, episode_id: str, record: CheckedDialogueRecord) -> str:
        key = artifact_key(episode_id, record.block.block_id)
        await self._storage.put(
            key,
            record.model_dump_json().encode("utf-8"),
            "application/json",
            {"schema_version": record.schema_version, "slot_id": record.block.slot_id},
        )
        return key

    async def save_audio(
        self, episode_id: str, block_id: str, snapshot: DialogueAudioSnapshot
    ) -> str:
        """Keep the request a passage was voiced with and the asset it produced."""
        key = audio_snapshot_key(episode_id, block_id)
        await self._storage.put(
            key,
            snapshot.model_dump_json().encode("utf-8"),
            "application/json",
            {"schema_version": snapshot.schema_version, "cache_key": snapshot.cache_key},
        )
        return key

    async def load_audio(self, episode_id: str, block_id: str) -> DialogueAudioSnapshot | None:
        stored = await self._storage.get(audio_snapshot_key(episode_id, block_id))
        if stored is None:
            return None
        content = getattr(stored, "content", None)
        if not isinstance(content, bytes):
            raise DialogueArtifactError("stored audio snapshot has no readable content")
        version = _declared_version(content)
        if version is _MISSING:
            raise DialogueArtifactError("stored audio snapshot does not declare a schema_version")
        if type(version) is not int or version != 1:
            raise DialogueArtifactError(f"unsupported audio snapshot schema_version {version!r}")
        try:
            return DialogueAudioSnapshot.model_validate_json(content)
        except ValidationError as error:
            raise DialogueArtifactError("stored audio snapshot is damaged or inconsistent") from error

    async def load(self, episode_id: str, block_id: str) -> CheckedDialogueRecord | None:
        stored = await self._storage.get(artifact_key(episode_id, block_id))
        if stored is None:
            return None
        content = getattr(stored, "content", None)
        if not isinstance(content, bytes):
            raise DialogueArtifactError("stored passage has no readable content")
        version = _declared_version(content)
        if version is _MISSING:
            raise DialogueArtifactError("stored passage does not declare a schema_version")
        if type(version) is not int or version != 1:  # True == 1 must not pass
            raise DialogueArtifactError(f"unsupported passage schema_version {version!r}")
        try:
            record = CheckedDialogueRecord.model_validate_json(content)
        except ValidationError as error:
            raise DialogueArtifactError("stored passage is damaged or inconsistent") from error
        if record.block.block_id != block_id:
            raise DialogueArtifactError("stored passage belongs to another block")
        return record


_MISSING = object()


def _declared_version(content: bytes) -> object:
    try:
        payload = json.loads(content)
    except ValueError as error:
        raise DialogueArtifactError("stored passage is damaged or inconsistent") from error
    if not isinstance(payload, dict) or "schema_version" not in payload:
        return _MISSING
    return payload["schema_version"]
