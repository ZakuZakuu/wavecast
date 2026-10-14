"""Shared story material → two-host draft → fact check (→ bounded repair) → a checked passage.

One passage costs at most ``max_calls`` model calls after the material exists (default 4: the
draft, the check, one repair of the flagged turns, one re-check).  The material is shared across
a programme's passages and is made once, outside this budget.  Nothing here rewrites a passage
as a whole: when the check finds a problem only the flagged turns are rewritten, with the
speakers and the number of turns kept; if that does not clear the check the passage is
*rejected* and the music simply carries on.  A passage that passes the first check is returned
untouched.  A short passage is never padded; there is no minimum length.

Cancellation is never swallowed.  A provider failure does not raise: it ends the passage as
rejected, with the reason, so the caller can keep the music going.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum

from wavecast.models.dialogue import (
    DialogueBlock,
    DialogueDraft,
    DialogueIssue,
    DialogueTurn,
)
from wavecast.models.story_material import StoryMaterial
from wavecast.providers.config import ProviderSettings
from wavecast.providers.contracts import ProgressiveLLMProvider
from wavecast.providers.errors import ProviderError
from wavecast.providers.llm_factory import build_llm
from wavecast.providers.usage import UsageLedger
from wavecast.stations import StationId
from wavecast.storage.dialogue_artifacts import CheckedDialogueRecord

from .dialogue import DialogueValidationError, block_from_draft, validate_dialogue_block
from .dialogue_budget import dialogue_budget_for, estimate_dialogue_seconds
from .dialogue_check import DialogueCheckReport, DialogueFactChecker
from .dialogue_writer import DialogueRepair, DialogueRepairer, DialogueSlot, DialogueWriter
from .story_material import StoryMaterialService

logger = logging.getLogger(__name__)

DEFAULT_MAX_CALLS = 4


class DialogueStatus(StrEnum):
    READY = "ready"  # passed the first check unchanged
    REPAIRED = "repaired"  # flagged turns were rewritten and the re-check passed
    REJECTED = "rejected"  # not to be voiced; ``reason`` says why
    SKIPPED = "skipped"  # nothing was attempted (no budget for this station)


@dataclass
class DialogueOutcome:
    status: DialogueStatus
    reason: str | None = None
    block: DialogueBlock | None = None
    material: StoryMaterial | None = None
    first_check_issues: list[DialogueIssue] = field(default_factory=list)
    final_issues: list[DialogueIssue] = field(default_factory=list)
    repaired_turns: list[int] = field(default_factory=list)
    calls: int = 0
    model_checked: bool = False
    station_value: str = ""

    @property
    def speakable(self) -> bool:
        return self.status in (DialogueStatus.READY, DialogueStatus.REPAIRED)

    def to_record(self) -> CheckedDialogueRecord:
        """The savable form.  Only a passage that may be voiced has one."""
        if not self.speakable or self.block is None or self.material is None:
            raise ValueError(f"a {self.status.value} passage cannot be saved as checked")
        return CheckedDialogueRecord(
            station=StationId(self.station_value),
            status="ready" if self.status is DialogueStatus.READY else "repaired",
            block=self.block,
            material=self.material,
            repaired_turns=self.repaired_turns,
            first_check_issues=self.first_check_issues,
            calls_used=self.calls,
            model_checked=self.model_checked,
        )


class _BudgetExhausted(Exception):
    pass


class _Calls:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.used = 0

    def take(self) -> None:
        if self.used >= self.limit:
            raise _BudgetExhausted
        self.used += 1


class DialoguePipeline:
    def __init__(
        self,
        *,
        writer: DialogueWriter,
        checker: DialogueFactChecker,
        repairer: DialogueRepairer,
        max_calls: int = DEFAULT_MAX_CALLS,
    ) -> None:
        if max_calls < 1:
            raise ValueError("max_calls must be at least one")
        self._writer = writer
        self._checker = checker
        self._repairer = repairer
        self._max_calls = max_calls

    async def produce(self, material: StoryMaterial, slot: DialogueSlot) -> DialogueOutcome:
        budget = dialogue_budget_for(slot.station)
        outcome = DialogueOutcome(
            status=DialogueStatus.REJECTED, material=material, station_value=slot.station.value
        )
        if budget is None:
            outcome.status = DialogueStatus.SKIPPED
            outcome.reason = "station_has_no_dialogue"
            return outcome
        calls = _Calls(self._max_calls)
        try:
            return await self._run(material, slot, budget.hard_max_seconds, calls, outcome)
        except _BudgetExhausted:
            outcome.reason = "budget_exhausted"
        except ProviderError as error:
            outcome.reason = f"provider_failed:{type(error).__name__}"
        outcome.status = DialogueStatus.REJECTED
        outcome.calls = calls.used
        return outcome

    async def _run(
        self,
        material: StoryMaterial,
        slot: DialogueSlot,
        hard_max_seconds: int,
        calls: _Calls,
        outcome: DialogueOutcome,
    ) -> DialogueOutcome:
        budget = dialogue_budget_for(slot.station)
        assert budget is not None
        calls.take()
        draft = await self._writer.write(material, slot, budget)
        block = self._to_block(draft, material, slot, outcome)
        if block is None:
            outcome.calls = calls.used
            return outcome
        if block.duration_seconds > hard_max_seconds:
            outcome.reason = "too_long"
            outcome.calls = calls.used
            return outcome

        calls.take()
        first = await self._checker.review(block, material)
        outcome.first_check_issues = list(first.issues)
        outcome.model_checked = first.model_checked
        if not first.issues:
            return self._accept(outcome, block, DialogueStatus.READY, first, calls)

        flagged = first.flagged_turns()
        if len(flagged) > (len(block.turns) + 1) // 2:
            outcome.reason = "too_many_flagged_turns"
            outcome.final_issues = list(first.issues)
            outcome.calls = calls.used
            return outcome

        calls.take()
        repair = await self._repairer.repair(block, material, flagged)
        repaired = self._apply(block, repair, set(flagged), material)
        if repaired is None:
            outcome.reason = "invalid_repair"
            outcome.final_issues = list(first.issues)
            outcome.calls = calls.used
            return outcome

        calls.take()
        second = await self._checker.review(repaired, material)
        outcome.model_checked = outcome.model_checked and second.model_checked
        if second.issues:
            outcome.reason = "unresolved_after_repair"
            outcome.final_issues = list(second.issues)
            outcome.calls = calls.used
            return outcome
        outcome.repaired_turns = sorted(flagged)
        return self._accept(outcome, repaired, DialogueStatus.REPAIRED, second, calls)

    @staticmethod
    def _accept(
        outcome: DialogueOutcome,
        block: DialogueBlock,
        status: DialogueStatus,
        report: DialogueCheckReport,
        calls: _Calls,
    ) -> DialogueOutcome:
        outcome.status = status
        outcome.block = block
        outcome.reason = None
        outcome.final_issues = []
        outcome.calls = calls.used
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
            )
        except DialogueValidationError as error:
            outcome.reason = "invalid_draft"
            outcome.final_issues = [
                DialogueIssue(turn=0, sentence=0, code="invalid_draft", message=problem[:600])
                for problem in error.problems
            ]
            return None

    @staticmethod
    def _apply(
        block: DialogueBlock,
        repair: DialogueRepair,
        flagged: set[int],
        material: StoryMaterial,
    ) -> DialogueBlock | None:
        """Replace the flagged turns' text and references; speakers and turn count are kept."""
        fixes = {fix.turn: fix for fix in repair.fixes}
        if len(fixes) != len(repair.fixes) or not fixes or not set(fixes) <= flagged:
            return None
        turns: list[DialogueTurn] = []
        try:
            for index, turn in enumerate(block.turns):
                fix = fixes.get(index)
                turns.append(
                    turn
                    if fix is None
                    # The text changed, so a pronunciation rendering of the old text is dropped.
                    else DialogueTurn(
                        speaker=turn.speaker, text=fix.text.strip(), tts_text=None, fact_refs=fix.fact_refs
                    )
                )
            repaired = block.model_copy(
                update={
                    "turns": turns,
                    "duration_seconds": estimate_dialogue_seconds(sum(len(t.text) for t in turns)),
                }
            )
            repaired = DialogueBlock.model_validate(repaired.model_dump())
            return validate_dialogue_block(
                repaired, allowed_fact_refs=material.fact_ids, expected_slot_id=block.slot_id
            )
        except (ValueError, DialogueValidationError):
            return None


@dataclass
class DialogueStack:
    """The three model roles of the dialogue path, built from the role configuration.

    ``material``, ``writer`` and ``fact_check`` are bound independently (the repair step uses
    the Writer's model).  Not wired into episode assembly yet.
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
    max_calls: int = DEFAULT_MAX_CALLS,
) -> DialogueStack:
    material_llm = build_llm(settings, "material", ledger=ledger, mock=mock)
    writer_llm = build_llm(settings, "writer", ledger=ledger, mock=mock)
    fact_check_llm = build_llm(settings, "fact_check", ledger=ledger, mock=mock)
    return DialogueStack(
        material=StoryMaterialService(material_llm),
        pipeline=DialoguePipeline(
            writer=DialogueWriter(writer_llm),
            checker=DialogueFactChecker(fact_check_llm),
            repairer=DialogueRepairer(writer_llm),
            max_calls=max_calls,
        ),
        owned_clients=[material_llm, writer_llm, fact_check_llm],
    )
