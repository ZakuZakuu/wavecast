"""Typed, slot-aware human-review artifacts for Chinese radio writing."""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from wavecast.intelligence.models import NarrationSlotContext, RadioScriptBlockKind

from .quality import PHASE53_RADIO_WRITING_RUBRIC, RadioWritingCriterion, RadioWritingRubric


class RadioWritingEvidenceMode(StrEnum):
    SUPPORTED = "supported"
    EMPTY = "empty"


class RadioWritingReviewExample(BaseModel):
    """A self-authored weak/strong comparison bound to one playback slot."""

    example_id: str = Field(min_length=1, max_length=80)
    slot_context: NarrationSlotContext
    block_kind: RadioScriptBlockKind
    weak_text: str = Field(min_length=1, max_length=500)
    stronger_text: str = Field(min_length=1, max_length=500)
    criteria: list[RadioWritingCriterion] = Field(min_length=1, max_length=4)
    evidence_mode: RadioWritingEvidenceMode
    reviewer_note: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_slot_kind(self) -> RadioWritingReviewExample:
        if self.block_kind not in self.slot_context.allowed_block_kinds:
            raise ValueError(
                f"{self.block_kind.value} is not allowed by slot {self.slot_context.slot_id}"
            )
        return self


class Phase53CRadioWritingReviewBundle(BaseModel):
    """Human-review material; it deliberately has no automatic quality score."""

    bundle_id: str = Field(min_length=1, max_length=100)
    language: Literal["zh-CN"] = "zh-CN"
    rubric: RadioWritingRubric
    examples: list[RadioWritingReviewExample] = Field(min_length=4, max_length=8)
    review_status: Literal["human_review_required"] = "human_review_required"


def build_phase53c_radio_writing_review_bundle(
    examples: Sequence[RadioWritingReviewExample],
    *,
    rubric: RadioWritingRubric = PHASE53_RADIO_WRITING_RUBRIC,
) -> Phase53CRadioWritingReviewBundle:
    """Assemble typed review material without judging the prose automatically."""

    return Phase53CRadioWritingReviewBundle(
        bundle_id="phase53c-radio-writing-offline-sanity",
        rubric=rubric,
        examples=list(examples),
    )
