"""From a validated two-host passage to a segment the existing timeline understands.

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
from wavecast.materialization.narration import NarrationMaterializer
from wavecast.models.dialogue import DialoguePurpose
from wavecast.models.episode import NarrationRole, NarrationSegment, SegmentState
from wavecast.models.story_material import StoryMaterial
from wavecast.models.story_usage import Reservation, StoryUseState
from wavecast.storage.dialogue_artifacts import (
    CheckedDialogueRecord,
    DialogueArtifactError,
    DialogueArtifactStore,
    artifact_key,
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
    """Rebuild the segment from the saved record: no model call, no new audio.

    If the passage was voiced, the segment carries the snapshot of that request, so voicing it
    again *restores* the original audio with its original voices - whatever the configuration
    says today.  Making new audio is :func:`regenerate_segment`, an explicit act.
    """
    record = await artifacts.load(episode_id, block_id)
    if record is None:
        return None
    segment = narration_segment_from_record(record, chapter_id=chapter_id, order=order)
    snapshot = await artifacts.load_audio(episode_id, block_id)
    if snapshot is not None:
        covered = {voice.speaker for voice in snapshot.voices}
        if not {turn.speaker for turn in record.block.turns} <= covered:
            raise DialogueArtifactError("the saved audio snapshot does not cover the speakers")
        segment.dialogue_audio = snapshot
    return segment


async def voice_segment(
    materializer: NarrationMaterializer,
    artifacts: DialogueArtifactStore,
    episode_id: str,
    segment: NarrationSegment,
) -> NarrationSegment:
    """Voice a dialogue segment (restoring it if it was voiced before) and keep its snapshot.

    The snapshot is saved the first time only: it is the record of what the audio was made with,
    and a later restore must not overwrite it with whatever is configured now.
    """
    block = segment.dialogue
    if block is None:
        raise ValueError("only a dialogue segment is voiced here")
    await materializer.materialize(segment)
    if segment.dialogue_audio is not None and await artifacts.load_audio(episode_id, block.block_id) is None:
        await artifacts.save_audio(episode_id, block.block_id, segment.dialogue_audio)
    return segment


async def regenerate_segment(
    materializer: NarrationMaterializer,
    artifacts: DialogueArtifactStore,
    episode_id: str,
    segment: NarrationSegment,
) -> NarrationSegment:
    """Make *new* audio for a dialogue under the current configuration, and record it.

    This is the one place a saved snapshot is replaced.  It refuses audio the listener has
    reached, and leaves the previous audio and snapshot untouched if making the new audio fails.
    """
    block = segment.dialogue
    if block is None:
        raise ValueError("only a dialogue segment can be regenerated")
    # Keep the current segment authoritative until the replacement snapshot is durable.
    # Synthesis can succeed while saving is cancelled or fails; that must not leave the
    # in-memory programme pointing at audio that its saved record does not describe.
    replacement = segment.model_copy(deep=True)
    await materializer.regenerate_dialogue(replacement)
    assert replacement.dialogue_audio is not None
    await artifacts.save_audio(episode_id, block.block_id, replacement.dialogue_audio)
    segment.asset_ref = replacement.asset_ref
    segment.audio_source_url = replacement.audio_source_url
    segment.actual_duration_seconds = replacement.actual_duration_seconds
    segment.dialogue_audio = replacement.dialogue_audio
    segment.state = replacement.state
    return segment


def saved_passage_matches(record: CheckedDialogueRecord, story_id: str, slot: DialogueSlot) -> bool:
    """Whether a saved passage is the one asked for: same story, same slot, same station.

    A block id alone only names a place in the programme.  If the route changed so that the
    place now holds another song, the passage saved there (and the audio made from it) is about
    the old song and must not be reused.
    """
    return (
        record.block.story_id == story_id
        and record.material.story_id == story_id
        and record.block.slot_id == slot.slot_id
        and record.station == slot.station
    )


@dataclass
class DialogueSeamResult:
    outcome: DialogueOutcome
    segment: NarrationSegment | None = None
    artifact_key: str | None = None
    reason: str | None = None
    # True when this is the passage that was already made (saved), handed back instead of a new
    # one: asking again for the same passage never writes anything a second time.
    restored: bool = False


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
        """Make, validate, save and package one passage - or give the story back and say why not."""
        story_id, block_id = material.story_id, slot.block_id
        reservation = await self._usage.reserve(episode_id, story_id, block_id)
        if reservation is Reservation.TAKEN:
            skipped = DialogueOutcome(
                status=DialogueStatus.SKIPPED,
                reason="story_already_used",
                material=material,
                station_value=slot.station.value,
            )
            return DialogueSeamResult(outcome=skipped, reason="story_already_used")
        if reservation is not Reservation.ACQUIRED:
            # The same passage again: either it is still being made, or it is made (and perhaps
            # already published).  Neither starts another Writer run.
            return await self._existing(
                episode_id,
                material,
                slot,
                chapter_id=chapter_id,
                order=order,
                told=reservation is Reservation.TOLD,
            )
        try:
            saved = await self._artifacts.load(episode_id, block_id)
            if saved is not None and not saved_passage_matches(saved, story_id, slot):
                # The place holds a passage about another story; writing here would replace it.
                await self._usage.release(episode_id, story_id, block_id)
                skipped = DialogueOutcome(
                    status=DialogueStatus.SKIPPED,
                    reason="saved_passage_is_for_another_story",
                    material=material,
                    station_value=slot.station.value,
                )
                return DialogueSeamResult(outcome=skipped, reason=skipped.reason)
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

    async def resume(
        self,
        episode_id: str,
        story_id: str,
        slot: DialogueSlot,
        *,
        chapter_id: str,
        order: int,
    ) -> DialogueSeamResult | None:
        """What is already known about this passage, learned *before* any model is asked.

        ``None`` means nothing is known and the caller should extract material and ``author``.
        Otherwise the answer needs no model call: the story belongs to another passage or is
        told (skip it), this passage is being made elsewhere (skip), or it was saved already and
        is handed back with the audio snapshot it was voiced with, if any.  This only reads;
        taking a story still goes through ``author``'s reservation, which stays the authority
        when two callers race.
        """
        block_id = slot.block_id
        entry = (await self._usage.load(episode_id)).entries.get(story_id)

        def skipped(reason: str) -> DialogueSeamResult:
            outcome = DialogueOutcome(
                status=DialogueStatus.SKIPPED, reason=reason, station_value=slot.station.value
            )
            return DialogueSeamResult(outcome=outcome, reason=reason)

        if entry is not None and entry.block_id != block_id:
            return skipped("story_already_used")
        if entry is not None and entry.state is StoryUseState.PUBLISHED:
            return skipped("already_told")  # a told passage is never re-entered
        record = await self._artifacts.load(episode_id, block_id)
        if record is None:
            return skipped("in_progress") if entry is not None else None
        if not saved_passage_matches(record, story_id, slot):
            # Something else was saved at this place.  Neither its text nor its audio is used,
            # and nothing is reserved for it: the caller falls back to the usual path.
            return skipped("saved_passage_is_for_another_story")
        if entry is None:
            # Saved, but its story went back to the pool (e.g. a reconcile of a lost segment):
            # take it again through the ledger rather than writing the passage a second time.
            if await self._usage.reserve(episode_id, story_id, block_id) is Reservation.TAKEN:
                return skipped("story_already_used")
        segment = await restore_narration_segment(
            self._artifacts, episode_id, block_id, chapter_id=chapter_id, order=order
        )
        return DialogueSeamResult(
            outcome=DialogueOutcome.from_record(record),
            segment=segment,
            artifact_key=artifact_key(episode_id, block_id),
            reason="resumed",
            restored=True,
        )

    async def _existing(
        self,
        episode_id: str,
        material: StoryMaterial,
        slot: DialogueSlot,
        *,
        chapter_id: str,
        order: int,
        told: bool,
    ) -> DialogueSeamResult:
        reason = "already_told" if told else "in_progress"
        record = await self._artifacts.load(episode_id, slot.block_id)
        if record is not None and not saved_passage_matches(record, material.story_id, slot):
            skipped = DialogueOutcome(
                status=DialogueStatus.SKIPPED,
                reason="saved_passage_is_for_another_story",
                material=material,
                station_value=slot.station.value,
            )
            return DialogueSeamResult(outcome=skipped, reason=skipped.reason)
        if record is None:
            # Reserved but not saved yet: somebody else is making it (or it was interrupted;
            # ``release_orphans`` frees a reservation that never arrived).
            pending = DialogueOutcome(
                status=DialogueStatus.SKIPPED,
                reason=reason,
                material=material,
                station_value=slot.station.value,
            )
            return DialogueSeamResult(outcome=pending, reason=reason)
        segment = await restore_narration_segment(
            self._artifacts, episode_id, slot.block_id, chapter_id=chapter_id, order=order
        )
        return DialogueSeamResult(
            outcome=DialogueOutcome.from_record(record),
            segment=segment,
            artifact_key=artifact_key(episode_id, slot.block_id),
            reason=reason,
            restored=True,
        )


__all__ = [
    "DialogueArtifactError",
    "DialogueSeamResult",
    "DialogueSeamService",
    "narration_segment_from_record",
    "saved_passage_matches",
    "regenerate_segment",
    "restore_narration_segment",
    "voice_segment",
]
