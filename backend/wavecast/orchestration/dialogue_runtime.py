"""Where a researched two-host passage enters live authoring - and where it gives up.

The Writer path stays the way a chapter's narration is made.  This is an *offer* made before it:
if the slot may carry a story passage, the researched evidence for the chapter's song is turned
into shared material, written as a two-host passage, validated and saved; the caller then
puts the saved passage into the chapter like any other narration block.  Every way this can
fail - no budget for the station, a slot the station gave to the Writer, too little evidence,
a provider error, a passage that failed validation - returns ``None`` and the chapter is
authored exactly as it was before, so the feature can only ever add a passage, never remove one.

Cancellation is never swallowed.  The story the passage tells is reserved while it is made;
``release`` gives it back if the passage is not used after all, and ``settle`` reconciles the
ledger with what the programme actually contains.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from wavecast.intelligence.dialogue_budget import dialogue_budget_for, story_slot_ids
from wavecast.intelligence.dialogue_writer import DialogueSlot
from wavecast.intelligence.models import Evidence, NarrationSlotContext
from wavecast.intelligence.story_material import StoryMaterialService
from wavecast.models.dialogue import DialogueAudioSnapshot, DialogueBlock, DialoguePurpose
from wavecast.models.episode import MusicSegment, NarrationSegment
from wavecast.orchestration.dialogue_timeline import DialogueSeamService
from wavecast.spoken_form import KnownTrack
from wavecast.stations import StationId
from wavecast.storage.dialogue_artifacts import DialogueArtifactStore
from wavecast.storage.story_usage import StoryUsageStore

logger = logging.getLogger(__name__)


def slot_may_carry_story(context_group: Sequence[NarrationSlotContext]) -> bool:
    """A story passage sits alone between two songs: not the opening, not the sign-off."""

    if len(context_group) != 1:
        return False
    context = context_group[0]
    return not context.is_opening and not context.is_final


def story_id_for(track_ref: str) -> str:
    """One story per song, stable across retries and resumes."""

    return "st-" + hashlib.sha256(track_ref.encode("utf-8")).hexdigest()[:12]


def block_id_for(slot_id: str) -> str:
    return f"dlg-{slot_id}"


@dataclass(frozen=True)
class DialogueOffer:
    """A passage to place in the chapter, and - when it was voiced before - how."""

    block: DialogueBlock
    # The request snapshot the saved audio was made with.  Carried onto the segment so that
    # voicing it again restores that audio with those voices, whatever is configured now.
    audio: DialogueAudioSnapshot | None = None
    restored: bool = False


class DialogueRuntime:
    def __init__(
        self,
        *,
        material: StoryMaterialService,
        seam: DialogueSeamService,
        usage: StoryUsageStore,
        artifacts: DialogueArtifactStore,
    ) -> None:
        self._material = material
        self._seam = seam
        self._usage = usage
        self._artifacts = artifacts

    def eligible_slot_ids(
        self, station: StationId | None, groups: Iterable[Sequence[NarrationSlotContext]], seed: str
    ) -> set[str]:
        """The slots of the programme that may carry a story, by the station's soft share."""

        if station is None or dialogue_budget_for(station) is None:
            return set()
        population = [
            group[0].slot_id for group in groups if slot_may_carry_story(group)
        ]
        return set(story_slot_ids(station, population, seed))

    async def offer(
        self,
        *,
        episode_id: str,
        station: StationId | None,
        context: NarrationSlotContext,
        chosen_slot_ids: set[str],
        chapter_id: str,
        order: int,
        evidence: Sequence[Evidence],
        subject: str,
        track_ref: str | None,
        track_label: str,
        previous_context: str = "",
        editorial_goal: str = "",
        programme_brief: str = "",
    ) -> DialogueOffer | None:
        """A validated, saved passage for this slot, or ``None`` (the Writer path then runs).

        What the ledger and the store already know is consulted *before* any model is asked: a
        saved passage is handed back (with its audio snapshot) at no cost, and a story held by
        another passage, told, or being made elsewhere is skipped without a request.
        """

        if (
            station is None
            or track_ref is None
            or context.slot_id not in chosen_slot_ids
            or not evidence
        ):
            return None
        story_id = story_id_for(track_ref)
        slot = DialogueSlot(
            slot_id=context.slot_id,
            block_id=block_id_for(context.slot_id),
            purpose=DialoguePurpose.STORY,
            station=station,
            just_played=(
                context.just_played_track.canonical_title
                if context.just_played_track is not None
                else None
            ),
            upcoming=(
                context.upcoming_track.canonical_title
                if context.upcoming_track is not None
                else None
            ),
            previous_context=previous_context,
            editorial_goal=editorial_goal,
            programme_brief=programme_brief,
            tracks=tuple(
                KnownTrack(track.canonical_artist, track.canonical_title, track.spoken_title)
                for track in (context.just_played_track, context.upcoming_track)
                if track is not None
            ),
        )
        try:
            result = await self._seam.resume(
                episode_id, story_id, slot, chapter_id=chapter_id, order=order
            )
            if result is None:
                material = await self._material.extract(
                    evidence,
                    story_id=story_id,
                    subject=track_label or subject,
                    recording_refs=[track_ref],
                )
                if material is None:
                    logger.info("dialogue_skipped slot_id=%s reason=thin_material", context.slot_id)
                    return None
                result = await self._seam.author(
                    episode_id, material, slot, chapter_id=chapter_id, order=order
                )
        except Exception as error:  # noqa: BLE001 - the Writer path must always remain available
            logger.warning(
                "dialogue_skipped slot_id=%s reason=error error_type=%s",
                context.slot_id,
                type(error).__name__,
            )
            return None
        segment = result.segment
        if segment is None or segment.dialogue is None:
            logger.info("dialogue_skipped slot_id=%s reason=%s", context.slot_id, result.reason)
            return None
        return DialogueOffer(
            block=segment.dialogue, audio=segment.dialogue_audio, restored=result.restored
        )

    async def release(self, episode_id: str, block: DialogueBlock) -> None:
        """Give the story back: the passage was made but never became part of the programme."""

        if block.story_id is None:
            return
        try:
            await self._usage.release(episode_id, block.story_id, block.block_id)
        except ValueError:
            pass  # already told: a told story stays told

    async def record_audio(self, episode_id: str, segment: NarrationSegment) -> None:
        """Keep, beside the saved passage, the request its audio was made with (first time only)."""

        block, snapshot = segment.dialogue, segment.dialogue_audio
        if block is None or snapshot is None:
            return
        if await self._artifacts.load_audio(episode_id, block.block_id) is None:
            await self._artifacts.save_audio(episode_id, block.block_id, snapshot)

    async def settle(
        self, episode_id: str, segments: Sequence[MusicSegment | NarrationSegment]
    ) -> None:
        """Bring the ledger in line with the programme: told stories stay told, lost ones return.

        Run when no authoring for this episode is in flight.  A passage the listener reached is
        published; one that was skipped is released; a reservation whose passage never reached
        the timeline (a crash, a chapter that went by) is released too.
        """

        await self._usage.reconcile(episode_id, segments)
        live = [
            segment.dialogue.block_id
            for segment in segments
            if isinstance(segment, NarrationSegment) and segment.dialogue is not None
        ]
        orphans = await self._usage.release_orphans(episode_id, live)
        if orphans:
            logger.info("dialogue_story_released episode_id=%s stories=%s", episode_id, len(orphans))
