"""From a checked two-host passage to a segment the existing timeline understands.

The passage is saved first, the story it tells is reserved, and the segment it becomes is an
ordinary ``NarrationSegment`` (SCRIPT_READY, carrying the dialogue).  From there the existing
machinery applies unchanged: authoring inserts it unless playback has already reached the
chapter, the materializer voices it as one audio asset whose *actual* length the arrangement
uses, and a segment that is skipped or late never touches what was already published.

Nothing here calls a model for text or audio: the passage comes from the pipeline's output (or
from a saved record), the audio from a speech provider, and both are passed in.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from wavecast.intelligence.dialogue_pipeline import (
    DialogueOutcome,
    DialoguePipeline,
    DialogueStatus,
)
from wavecast.intelligence.dialogue_writer import DialogueSlot
from wavecast.models.dialogue import DialoguePurpose
from wavecast.models.episode import NarrationRole, NarrationSegment, SegmentState
from wavecast.models.story_material import StoryMaterial
from wavecast.storage.dialogue_artifacts import (
    CheckedDialogueRecord,
    DialogueArtifactError,
    DialogueArtifactStore,
)
from wavecast.storage.story_usage import StoryUsageStore

logger = logging.getLogger(__name__)

# Story passages sit between two songs in the first version (never over a vocal).
_ROLE_FOR_PURPOSE = {
    DialoguePurpose.OPENING: NarrationRole.INTRO,
    DialoguePurpose.TRANSITION: NarrationRole.TRANSITION,
    DialoguePurpose.STORY: NarrationRole.TRANSITION,
    DialoguePurpose.OUTRO: NarrationRole.OUTRO,
}


def narration_segment_from_record(
    record: CheckedDialogueRecord, *, chapter_id: str, order: int
) -> NarrationSegment:
    """The unpublished, not-yet-voiced segment for a checked passage."""
    block = record.block
    return NarrationSegment(
        id=f"{chapter_id}:dialogue:{block.block_id}",
        chapter_id=chapter_id,
        order=order,
        state=SegmentState.SCRIPT_READY,
        planned_duration_seconds=block.duration_seconds,
        title="Story dialogue",
        narration_role=_ROLE_FOR_PURPOSE[block.purpose],
        dialogue=block,
    )


async def restore_narration_segment(
    artifacts: DialogueArtifactStore,
    episode_id: str,
    block_id: str,
    *,
    chapter_id: str,
    order: int,
) -> NarrationSegment | None:
    """Rebuild the segment from the saved record: no model call, no new check, no new audio."""
    record = await artifacts.load(episode_id, block_id)
    if record is None:
        return None
    return narration_segment_from_record(record, chapter_id=chapter_id, order=order)


@dataclass
class DialogueSeamResult:
    outcome: DialogueOutcome
    segment: NarrationSegment | None = None
    artifact_key: str | None = None
    reason: str | None = None


class DialogueSeamService:
    def __init__(
        self,
        *,
        pipeline: DialoguePipeline,
        artifacts: DialogueArtifactStore,
        usage: StoryUsageStore,
    ) -> None:
        self._pipeline = pipeline
        self._artifacts = artifacts
        self._usage = usage

    async def author(
        self,
        episode_id: str,
        material: StoryMaterial,
        slot: DialogueSlot,
        *,
        chapter_id: str,
        order: int,
    ) -> DialogueSeamResult:
        """Make, check, save and package one passage - or give the story back and say why not."""
        story_id, block_id = material.story_id, slot.block_id
        if not await self._usage.reserve(episode_id, story_id, block_id):
            skipped = DialogueOutcome(
                status=DialogueStatus.SKIPPED,
                reason="story_already_used",
                material=material,
                station_value=slot.station.value,
            )
            return DialogueSeamResult(outcome=skipped, reason="story_already_used")
        try:
            outcome = await self._pipeline.produce(material, slot)
            if not outcome.speakable:
                await self._usage.release(episode_id, story_id, block_id)
                return DialogueSeamResult(outcome=outcome, reason=outcome.reason)
            record = outcome.to_record()
            key = await self._artifacts.save(episode_id, record)
        except BaseException:  # includes cancellation: the story must not stay held
            await asyncio.shield(self._usage.release(episode_id, story_id, block_id))
            raise
        segment = narration_segment_from_record(record, chapter_id=chapter_id, order=order)
        return DialogueSeamResult(outcome=outcome, segment=segment, artifact_key=key)


__all__ = [
    "DialogueArtifactError",
    "DialogueSeamResult",
    "DialogueSeamService",
    "narration_segment_from_record",
    "restore_narration_segment",
]
