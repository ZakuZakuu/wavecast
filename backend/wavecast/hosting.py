"""A small, durable discussion schedule for the two editorial stations.

Counts describe voiced discussions, never drafts or generic handoffs. Older sessions without
this plan and the lighter stations retain their existing authoring policy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

from wavecast.presentation import HostMode
from wavecast.stations import StationId

if TYPE_CHECKING:
    from wavecast.models.episode import LiveEpisode
    from wavecast.models.progressive import ProgressiveAssemblyChapter


OPENING_SECONDS = 75
CLOSING_SECONDS = 45


class DiscussionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: int = Field(ge=1, le=16)
    minimum: int = Field(ge=1, le=16)
    chapter_ids: list[str] = Field(default_factory=list, max_length=16)
    backup_chapter_id: str | None = None
    # None is the older count-only plan. New plans reserve at most the first two gaps.
    opening_chapter_ids: list[str] | None = Field(default=None, max_length=2)


class HostingCoverage(BaseModel):
    target: int
    minimum: int
    delivered: int
    status: Literal["pending", "met", "shortfall"]
    reason: (
        Literal[
            "insufficient_slots",
            "discussion_not_delivered",
            "opening_not_delivered",
            "closing_not_delivered",
        ]
        | None
    ) = None
    opening: Literal["pending", "delivered", "missed"] | None = None
    closing: Literal["pending", "delivered", "missed"] | None = None


def discussion_counts(
    station: StationId | None, mode: HostMode, seconds: int
) -> tuple[int, int] | None:
    if station not in {StationId.PORTRAIT, StationId.LINEAGE} or mode is not HostMode.FULL:
        return None
    target = min(16, max(2, round(seconds / 900) + 1))
    return target, max(1, target - 1)


def discussion_seconds(station: StationId) -> int:
    from wavecast.intelligence.dialogue_budget import dialogue_budget_for

    budget = dialogue_budget_for(station)
    assert budget is not None
    return (budget.target_min_seconds + budget.target_max_seconds) // 2


def plan_discussions(
    chapters: list[ProgressiveAssemblyChapter], *, target: int, minimum: int
) -> DiscussionPlan:
    # Reserve the first two actual music gaps for the opening / its one early fallback.
    # Narrative-only chapters must not push the first substantive passage to mid-programme.
    opening_ids: list[str] = []
    music_before = 1
    for chapter in chapters:
        if music_before > 2:
            break
        if chapter.slot_contexts and not any(slot.is_final for slot in chapter.slot_contexts):
            if len(opening_ids) < music_before:
                opening_ids.append(chapter.chapter_id)
        if chapter.resolved_track is not None:
            music_before += 1
    # Keep the final slot for the closing, and the middle discussion target independent.
    # Quantiles of cumulative music time give a stable spread, also for uneven song lengths.
    elapsed = 0
    candidates: list[tuple[str, int]] = []
    for chapter in chapters:
        if (
            chapter.chapter_id not in opening_ids
            and chapter.resolved_track is not None
            and len(chapter.slot_contexts) == 1
            and not chapter.slot_contexts[0].is_opening
            and not chapter.slot_contexts[0].is_final
        ):
            candidates.append((chapter.chapter_id, elapsed))
        if chapter.resolved_track is not None:
            elapsed += chapter.resolved_track.duration_seconds or 210
    # One later seam is held back when the route has enough places for a genuine extra try.
    backup = candidates.pop()[0] if len(candidates) > target else None
    count = min(target, len(candidates))
    selected: set[str] = set()
    for index in range(count):
        position = candidates[0][1] + (candidates[-1][1] - candidates[0][1]) * (
            index / max(1, count - 1)
        )
        selected.add(
            min(
                (item for item in candidates if item[0] not in selected),
                key=lambda item: abs(item[1] - position),
            )[0]
        )
    return DiscussionPlan(
        target=target,
        minimum=minimum,
        chapter_ids=[cid for cid, _ in candidates if cid in selected],
        backup_chapter_id=backup,
        opening_chapter_ids=opening_ids,
    )


def has_programme_opening(episode: LiveEpisode, *, include_script: bool = False) -> bool:
    from wavecast.models.episode import NarrationSegment, SegmentState

    return any(
        isinstance(segment, NarrationSegment)
        and segment.hosting_role == "opening"
        and (
            segment.is_audio_ready
            or (include_script and segment.state is SegmentState.SCRIPT_READY)
        )
        and segment.state is not SegmentState.SKIPPED
        for segment in episode.timeline_segments
    )


def needs_programme_opening(episode: LiveEpisode, chapter_id: str) -> bool:
    session = episode.progressive_session
    plan = session.discussion_plan if session else None
    return bool(
        plan is not None
        and plan.opening_chapter_ids is not None
        and chapter_id in plan.opening_chapter_ids
        and not has_programme_opening(episode, include_script=True)
    )


def delivered_discussions(episode: LiveEpisode) -> int:
    from wavecast.models.dialogue import DialoguePurpose, DialogueSpeaker
    from wavecast.models.episode import NarrationSegment

    return sum(
        1
        for segment in episode.timeline_segments
        if isinstance(segment, NarrationSegment)
        and segment.is_audio_ready
        and (block := segment.dialogue) is not None
        and block.purpose in {DialoguePurpose.STORY, DialoguePurpose.OPENING}
        and segment.hosting_role != "opening"
        and len(block.turns) >= 3
        and {turn.speaker for turn in block.turns} == {DialogueSpeaker.A, DialogueSpeaker.B}
        and bool(block.fact_refs)
    )


def hosting_coverage(episode: LiveEpisode) -> HostingCoverage | None:
    from wavecast.models.episode import EpisodeState, NarrationSegment

    session = episode.progressive_session
    plan = session.discussion_plan if session else None
    if plan is None:
        return None
    delivered = delivered_discussions(episode)
    terminal = episode.state in {EpisodeState.MATERIALIZED, EpisodeState.PUBLISHED}
    bookends = plan.opening_chapter_ids is not None
    opened = has_programme_opening(episode)
    closed = any(
        isinstance(segment, NarrationSegment)
        and segment.hosting_role == "closing"
        and segment.is_audio_ready
        for segment in episode.timeline_segments
    )
    complete = delivered >= plan.minimum and (not bookends or (opened and closed))
    status: Literal["pending", "met", "shortfall"] = (
        "met" if complete else "shortfall" if terminal else "pending"
    )
    return HostingCoverage(
        target=plan.target,
        minimum=plan.minimum,
        delivered=delivered,
        status=status,
        opening=("delivered" if opened else "missed" if terminal else "pending")
        if bookends
        else None,
        closing=("delivered" if closed else "missed" if terminal else "pending")
        if bookends
        else None,
        reason=(
            "insufficient_slots"
            if len(plan.chapter_ids) < plan.minimum
            else "discussion_not_delivered"
        )
        if status == "shortfall" and delivered < plan.minimum
        else "opening_not_delivered"
        if status == "shortfall" and bookends and not opened
        else "closing_not_delivered"
        if status == "shortfall" and bookends and not closed
        else None,
    )


def backup_ready(episode: LiveEpisode) -> bool:
    """Wait for primary outcomes, not just for their Writer calls to finish."""
    from wavecast.models.episode import NarrationSegment, SegmentState

    session = episode.progressive_session
    plan = session.discussion_plan if session else None
    if plan is None or plan.backup_chapter_id is None or session is None:
        return False
    authored = set(session.narration_authored_chapter_ids)
    if plan.backup_chapter_id in authored or not set(plan.chapter_ids) <= authored:
        return False
    return not any(
        isinstance(segment, NarrationSegment)
        and segment.chapter_id in plan.chapter_ids
        and segment.state
        in {SegmentState.PLANNED, SegmentState.SCRIPT_READY, SegmentState.AUDIO_GENERATING}
        for segment in episode.segments
    )
