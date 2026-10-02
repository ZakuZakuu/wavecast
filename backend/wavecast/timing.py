"""Provider-neutral, deterministic program timing calculations.

Timing is an application concern. This module deliberately has no provider,
LLM, playback-clock, or lifecycle dependencies so that a program's requested
duration can be planned before Writer runs and audited after TTS completes.
"""

from __future__ import annotations

from decimal import ROUND_FLOOR, Decimal

from pydantic import BaseModel, Field, model_validator


class ChapterNarrationBudget(BaseModel):
    """The deterministic spoken-time allocation for one chapter."""

    chapter_index: int = Field(ge=0)
    slot_count: int = Field(ge=0)
    target_narration_seconds: int = Field(ge=0)


class ProgramTimingPlan(BaseModel):
    """A pre-Writer timing budget owned by the application."""

    desired_total_seconds: int = Field(gt=0)
    target_narration_ratio: float = Field(ge=0, le=1)
    resolved_music_seconds: int = Field(ge=0)
    requested_narration_seconds: int = Field(ge=0)
    available_narration_seconds: int = Field(ge=0)
    allocated_narration_seconds: int = Field(ge=0)
    duration_target_feasible: bool
    chapter_budgets: list[ChapterNarrationBudget] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_budget_sum(self) -> ProgramTimingPlan:
        if sum(item.target_narration_seconds for item in self.chapter_budgets) != self.allocated_narration_seconds:
            raise ValueError("chapter narration budgets must sum to allocated narration seconds")
        if self.duration_target_feasible and self.allocated_narration_seconds > self.available_narration_seconds:
            raise ValueError("a feasible timing plan cannot allocate more narration than available duration")
        if self.duration_target_feasible and self.resolved_music_seconds >= self.desired_total_seconds:
            raise ValueError("a feasible timing target cannot have music at or beyond the desired duration")
        return self


class ProgramTimingSummary(BaseModel):
    """Planned and actual timing diagnostics for an assembled episode."""

    desired_total_seconds: int = Field(gt=0)
    music_seconds: int = Field(ge=0)
    planned_narration_seconds: int = Field(ge=0)
    actual_narration_seconds: int = Field(ge=0)
    planned_total_seconds: int = Field(ge=0)
    actual_total_seconds: int = Field(ge=0)
    target_error_seconds: int
    planned_vs_actual_narration_error_seconds: int
    target_narration_ratio: float = Field(ge=0, le=1)
    planned_narration_ratio: float = Field(ge=0, le=1)
    actual_narration_ratio: float = Field(ge=0, le=1)
    duration_target_feasible: bool


def build_program_timing_plan(
    *,
    desired_total_seconds: int,
    target_narration_ratio: float,
    resolved_music_seconds: int,
    chapter_slot_counts: list[int],
) -> ProgramTimingPlan:
    """Build a deterministic weighted narration budget.

    A target is feasible when the remaining duration can hold the deterministic
    one-second minimum for every existing chapter. If the music leaves less
    room, each existing chapter still receives a one-second minimum budget and
    the explicit infeasible flag preserves the chapter/editorial structure
    instead of deleting content.
    """

    if desired_total_seconds <= 0:
        raise ValueError("desired_total_seconds must be positive")
    if not 0 <= target_narration_ratio <= 1:
        raise ValueError("target_narration_ratio must be between 0 and 1")
    if resolved_music_seconds < 0:
        raise ValueError("resolved_music_seconds cannot be negative")
    if any(count < 0 for count in chapter_slot_counts):
        raise ValueError("chapter slot counts cannot be negative")

    normalized_slots = list(chapter_slot_counts)
    requested = max(0, round(desired_total_seconds * target_narration_ratio))
    available = max(0, desired_total_seconds - resolved_music_seconds)
    active_slot_chapters = sum(count > 0 for count in normalized_slots)
    minimum_narration_seconds = active_slot_chapters
    feasible = (
        resolved_music_seconds < desired_total_seconds
        if active_slot_chapters == 0
        else available >= minimum_narration_seconds
    )
    if active_slot_chapters == 0:
        allocated = 0
    elif feasible:
        allocated = min(requested, available)
        allocated = max(allocated, minimum_narration_seconds)
    else:
        allocated = minimum_narration_seconds

    budgets = _weighted_budgets(normalized_slots, allocated)
    return ProgramTimingPlan(
        desired_total_seconds=desired_total_seconds,
        target_narration_ratio=target_narration_ratio,
        resolved_music_seconds=resolved_music_seconds,
        requested_narration_seconds=requested,
        available_narration_seconds=available,
        allocated_narration_seconds=allocated,
        duration_target_feasible=feasible,
        chapter_budgets=[
            ChapterNarrationBudget(
                chapter_index=index,
                slot_count=slot_count,
                target_narration_seconds=target,
            )
            for index, (slot_count, target) in enumerate(zip(normalized_slots, budgets, strict=True))
        ],
    )


def summarize_program_timing(
    plan: ProgramTimingPlan,
    *,
    planned_narration_seconds: int,
    actual_narration_seconds: int,
    music_seconds: int | None = None,
) -> ProgramTimingSummary:
    """Compare the deterministic plan with normalized script and TTS output."""

    actual_music = plan.resolved_music_seconds if music_seconds is None else music_seconds
    planned_total = actual_music + planned_narration_seconds
    actual_total = actual_music + actual_narration_seconds
    return ProgramTimingSummary(
        desired_total_seconds=plan.desired_total_seconds,
        music_seconds=actual_music,
        planned_narration_seconds=planned_narration_seconds,
        actual_narration_seconds=actual_narration_seconds,
        planned_total_seconds=planned_total,
        actual_total_seconds=actual_total,
        target_error_seconds=actual_total - plan.desired_total_seconds,
        planned_vs_actual_narration_error_seconds=actual_narration_seconds - planned_narration_seconds,
        target_narration_ratio=plan.target_narration_ratio,
        planned_narration_ratio=(planned_narration_seconds / planned_total) if planned_total else 0.0,
        actual_narration_ratio=(actual_narration_seconds / actual_total) if actual_total else 0.0,
        duration_target_feasible=plan.duration_target_feasible,
    )


def _weighted_budgets(weights: list[int], total: int) -> list[int]:
    if not weights:
        return []
    active = [index for index, weight in enumerate(weights) if weight > 0]
    if not active:
        return [0] * len(weights)

    minimum = len(active)
    total = max(total, minimum)
    remaining = total - minimum
    weight_sum = sum(weights[index] for index in active)
    exact = {
        index: Decimal(remaining * weights[index]) / Decimal(weight_sum)
        for index in active
    }
    floors = {
        index: int(value.to_integral_value(rounding=ROUND_FLOOR))
        for index, value in exact.items()
    }
    remainder = remaining - sum(floors.values())
    order = sorted(
        active,
        key=lambda index: (exact[index] - floors[index], -index),
        reverse=True,
    )
    for index in order[:remainder]:
        floors[index] += 1

    return [
        0 if weight == 0 else 1 + floors[index]
        for index, weight in enumerate(weights)
    ]
