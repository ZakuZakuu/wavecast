"""Shared story material → two-host draft → basic validation → a passage ready to voice.

One passage costs one model call after the material exists: the Writer's draft.  There is no
after-the-fact model check, repair or re-check (ADR 0029): what the hosts may say is bounded by
the verified material and the Writer's prompt, and code validates only the structure - speakers,
turn count, that every cited fact id belongs to this material, and the station's hard length
ceiling.  A draft that fails that validation is *rejected* and the music simply carries on.
Nothing is padded; there is no minimum length.

Cancellation is never swallowed.  A provider failure does not raise: it ends the passage as
rejected, with the reason, so the caller can keep the music going.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import StrEnum

from wavecast.models.dialogue import DialogueBlock, DialogueDraft, DialogueIssue
from wavecast.models.story_material import StoryMaterial
from wavecast.providers.config import ProviderSettings
from wavecast.providers.contracts import ProgressiveLLMProvider
from wavecast.providers.errors import ProviderError
from wavecast.providers.llm_factory import build_llm
from wavecast.providers.usage import UsageLedger
from wavecast.spoken_form import has_unspeakable_script, to_spoken_form
from wavecast.stations import StationId
from wavecast.storage.dialogue_artifacts import CheckedDialogueRecord

from .dialogue import DialogueValidationError, block_from_draft
from .dialogue_budget import dialogue_budget_for, estimate_dialogue_seconds
from .dialogue_writer import DialogueSlot, DialogueWriter
from .story_material import StoryMaterialService
from .time_guard import has_relative_time, invents_experience

logger = logging.getLogger(__name__)


class DialogueStatus(StrEnum):
    READY = "ready"  # validated; may be voiced (not model-checked: see ``model_checked``)
    REPAIRED = "repaired"  # only in records saved while a model check and repair still existed
    REJECTED = "rejected"  # not to be voiced; ``reason`` says why
    SKIPPED = "skipped"  # nothing was attempted (no budget for this station)


@dataclass
class DialogueOutcome:
    status: DialogueStatus
    reason: str | None = None
    block: DialogueBlock | None = None
    material: StoryMaterial | None = None
    # The next three are filled only from records saved while a model check still existed.
    first_check_issues: list[DialogueIssue] = field(default_factory=list)
    repaired_turns: list[int] = field(default_factory=list)
    final_issues: list[DialogueIssue] = field(default_factory=list)
    calls: int = 0
    # Honest by construction: no passage made now has been through a model check.
    model_checked: bool = False
    station_value: str = ""

    @classmethod
    def from_record(cls, record: CheckedDialogueRecord) -> DialogueOutcome:
        """The outcome of a passage that was already made and saved (nothing is called)."""
        return cls(
            status=DialogueStatus.READY if record.status == "ready" else DialogueStatus.REPAIRED,
            block=record.block,
            material=record.material,
            first_check_issues=list(record.first_check_issues),
            repaired_turns=list(record.repaired_turns),
            calls=0,
            model_checked=record.model_checked,
            station_value=record.station.value,
        )

    @property
    def speakable(self) -> bool:
        return self.status in (DialogueStatus.READY, DialogueStatus.REPAIRED)

    def to_record(self) -> CheckedDialogueRecord:
        """The savable form.  Only a passage that may be voiced has one."""
        if not self.speakable or self.block is None or self.material is None:
            raise ValueError(f"a {self.status.value} passage cannot be saved")
        return CheckedDialogueRecord(
            schema_version=1,
            station=StationId(self.station_value),
            status="ready" if self.status is DialogueStatus.READY else "repaired",
            block=self.block,
            material=self.material,
            repaired_turns=self.repaired_turns,
            first_check_issues=self.first_check_issues,
            calls_used=self.calls,
            model_checked=self.model_checked,
        )


class DialoguePipeline:
    def __init__(self, *, writer: DialogueWriter) -> None:
        self._writer = writer

    async def produce(self, material: StoryMaterial, slot: DialogueSlot) -> DialogueOutcome:
        budget = dialogue_budget_for(slot.station)
        outcome = DialogueOutcome(
            status=DialogueStatus.REJECTED, material=material, station_value=slot.station.value
        )
        if budget is None:
            outcome.status = DialogueStatus.SKIPPED
            outcome.reason = "station_has_no_dialogue"
            return outcome
        outcome.calls = 1
        try:
            draft = await self._writer.write(material, slot, budget)
        except asyncio.CancelledError:
            raise
        except ProviderError as error:
            outcome.reason = f"provider_failed:{type(error).__name__}"
            return outcome
        if any(has_relative_time(turn.text) or invents_experience(turn.text) for turn in draft.turns):
            # Said as it stands it would put an old page's "recently" into today, or give a host a
            # memory they do not have: no passage is better than a false one.
            logger.info("dialogue_rejected slot_id=%s reason=time_or_experience", slot.slot_id)
            outcome.reason = "time_or_experience"
            return outcome
        block = self._to_block(draft, material, slot, outcome)
        if block is None:
            return outcome
        # Only known names are converted; the authored lines and fact references stay intact.
        # Refuse unresolved names here so the existing single-host fallback still has a turn.
        for turn in block.turns:
            if not has_unspeakable_script(turn.text):
                continue
            spoken = to_spoken_form(turn.text, slot.tracks)
            if not spoken.ok:
                outcome.reason = "unspeakable_script"
                logger.info("dialogue_rejected slot_id=%s reason=unspeakable_script", slot.slot_id)
                return outcome
            turn.tts_text = spoken.tts_text
        if block.duration_seconds > budget.hard_max_seconds:
            outcome.reason = "too_long"
            return outcome
        outcome.status = DialogueStatus.READY
        outcome.block = block
        outcome.reason = None
        logger.info(
            "dialogue_passage status=ready turns=%d estimated_seconds=%d model_checked=false",
            len(block.turns),
            block.duration_seconds,
        )
        return outcome

    @staticmethod
    def _to_block(
        draft: DialogueDraft, material: StoryMaterial, slot: DialogueSlot, outcome: DialogueOutcome
    ) -> DialogueBlock | None:
        characters = sum(len(turn.text) for turn in draft.turns)
        try:
            return block_from_draft(
                draft,
                block_id=slot.block_id,
                slot_id=slot.slot_id,
                purpose=slot.purpose,
                duration_seconds=estimate_dialogue_seconds(characters),
                allowed_fact_refs=material.fact_ids,
                story_id=material.story_id,
            )
        except DialogueValidationError as error:
            outcome.reason = "invalid_draft"
            outcome.final_issues = [
                DialogueIssue(turn=0, sentence=0, code="invalid_draft", message=problem[:600])
                for problem in error.problems
            ]
            return None


@dataclass
class DialogueStack:
    """The two model roles of the dialogue path, built from the role configuration.

    ``material`` and ``writer`` are bound independently.
    """

    material: StoryMaterialService
    pipeline: DialoguePipeline
    owned_clients: list[object]

    async def aclose(self) -> None:
        """Close every distinct client once, even when one close fails."""
        closed: set[int] = set()
        first_error: Exception | None = None
        for client in self.owned_clients:
            close = getattr(client, "aclose", None)
            if not callable(close) or id(client) in closed:
                continue
            closed.add(id(client))
            try:
                result = close()
                if hasattr(result, "__await__"):
                    await result
            except Exception as error:  # noqa: BLE001 - keep closing the rest
                first_error = first_error or error
        if first_error is not None:
            raise first_error


def create_dialogue_stack(
    settings: ProviderSettings,
    *,
    ledger: UsageLedger,
    mock: ProgressiveLLMProvider,
) -> DialogueStack:
    material_llm = build_llm(settings, "material", ledger=ledger, mock=mock)
    writer_llm = build_llm(settings, "writer", ledger=ledger, mock=mock)
    return DialogueStack(
        material=StoryMaterialService(material_llm),
        pipeline=DialoguePipeline(writer=DialogueWriter(writer_llm)),
        owned_clients=[material_llm, writer_llm],
    )
