"""Provider-neutral music timing signals for narration-aware arrangement."""

from __future__ import annotations

from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field, model_validator


class TimingInterval(BaseModel):
    model_config = ConfigDict(frozen=True)

    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_interval(self) -> "TimingInterval":
        if self.end_seconds <= self.start_seconds:
            raise ValueError("timing interval end must be after start")
        return self


class TrackSectionKind(StrEnum):
    INTRO_INSTRUMENTAL = "INTRO_INSTRUMENTAL"
    VOCAL = "VOCAL"
    INSTRUMENTAL_GAP = "INSTRUMENTAL_GAP"
    OUTRO_INSTRUMENTAL = "OUTRO_INSTRUMENTAL"


class TrackSection(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: TrackSectionKind
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)


class TrackTimingProfile(BaseModel):
    """Timing-only analysis. No lyric text is persisted in the P0 contract."""

    model_config = ConfigDict(frozen=True)

    source_duration_seconds: float = Field(gt=0)
    lyric_timestamps_available: bool = False
    lyric_lines: tuple[TimingInterval, ...] = ()
    vocal_intervals: tuple[TimingInterval, ...] = ()
    sections: tuple[TrackSection, ...] = ()

    @model_validator(mode="after")
    def validate_bounds(self) -> "TrackTimingProfile":
        for interval in (*self.lyric_lines, *self.vocal_intervals):
            if interval.end_seconds > self.source_duration_seconds + 1e-6:
                raise ValueError("timing interval exceeds source duration")
        for section in self.sections:
            if section.end_seconds > self.source_duration_seconds + 1e-6:
                raise ValueError("track section exceeds source duration")
            if section.end_seconds <= section.start_seconds:
                raise ValueError("track section end must be after start")
        return self

    @property
    def first_vocal_start_seconds(self) -> float | None:
        return self.vocal_intervals[0].start_seconds if self.vocal_intervals else None

    @property
    def last_vocal_end_seconds(self) -> float | None:
        return self.vocal_intervals[-1].end_seconds if self.vocal_intervals else None


def track_timing_profile_from_payload(
    payload: object,
    *,
    fallback_duration_seconds: float | None = None,
) -> TrackTimingProfile | None:
    if not isinstance(payload, dict):
        return None
    raw_duration = payload.get("source_duration_seconds", fallback_duration_seconds)
    try:
        duration = float(raw_duration) if raw_duration is not None else 0.0
    except (TypeError, ValueError):
        duration = 0.0
    if duration <= 0:
        return None

    lyric_lines = _intervals(payload.get("lyric_lines"), duration)
    vocal_intervals = _intervals(payload.get("vocal_intervals"), duration)
    available = bool(payload.get("lyric_timestamps_available")) and bool(lyric_lines)

    base = TrackTimingProfile(
        source_duration_seconds=duration,
        lyric_timestamps_available=available,
        lyric_lines=tuple(lyric_lines),
        vocal_intervals=tuple(vocal_intervals),
    )
    return base.model_copy(update={"sections": _derive_sections(base)})


def safe_outgoing_narration_overlap_seconds(
    profile: TrackTimingProfile | None,
    *,
    fallback_seconds: float,
    max_seconds: float,
    guard_seconds: float = 0.75,
) -> float:
    """How much voice may safely enter before outgoing music ends."""

    if (
        profile is None
        or not profile.lyric_timestamps_available
        or not profile.vocal_intervals
    ):
        return max(0.0, fallback_seconds)
    last_vocal_end = profile.last_vocal_end_seconds
    assert last_vocal_end is not None
    trailing_instrumental = (
        profile.source_duration_seconds - last_vocal_end - guard_seconds
    )
    if trailing_instrumental <= 0:
        return 0.0
    return max(0.0, min(max_seconds, trailing_instrumental))


def safe_incoming_music_overlap_seconds(
    profile: TrackTimingProfile | None,
    *,
    fallback_seconds: float,
    guard_seconds: float = 0.75,
) -> float:
    """How early incoming music may start beneath narration before first vocal."""

    if (
        profile is None
        or not profile.lyric_timestamps_available
        or not profile.vocal_intervals
    ):
        return max(0.0, fallback_seconds)
    first_vocal_start = profile.first_vocal_start_seconds
    assert first_vocal_start is not None
    instrumental_intro = first_vocal_start - guard_seconds
    return max(0.0, min(fallback_seconds, instrumental_intro))


def _intervals(value: object, duration: float) -> list[TimingInterval]:
    if not isinstance(value, (list, tuple)):
        return []
    intervals: list[TimingInterval] = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        try:
            start = max(0.0, float(raw.get("start_seconds", 0)))
            end = min(duration, float(raw.get("end_seconds", 0)))
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        intervals.append(TimingInterval(start_seconds=start, end_seconds=end))
    return sorted(intervals, key=lambda item: (item.start_seconds, item.end_seconds))


def _derive_sections(profile: TrackTimingProfile) -> tuple[TrackSection, ...]:
    vocals = profile.vocal_intervals
    if not vocals:
        return ()
    sections: list[TrackSection] = []
    cursor = 0.0
    for index, vocal in enumerate(vocals):
        if vocal.start_seconds - cursor >= 2.0:
            sections.append(
                TrackSection(
                    kind=(
                        TrackSectionKind.INTRO_INSTRUMENTAL
                        if index == 0 and cursor == 0
                        else TrackSectionKind.INSTRUMENTAL_GAP
                    ),
                    start_seconds=cursor,
                    end_seconds=vocal.start_seconds,
                )
            )
        sections.append(
            TrackSection(
                kind=TrackSectionKind.VOCAL,
                start_seconds=vocal.start_seconds,
                end_seconds=vocal.end_seconds,
            )
        )
        cursor = max(cursor, vocal.end_seconds)
    if profile.source_duration_seconds - cursor >= 2.0:
        sections.append(
            TrackSection(
                kind=TrackSectionKind.OUTRO_INSTRUMENTAL,
                start_seconds=cursor,
                end_seconds=profile.source_duration_seconds,
            )
        )
    return tuple(sections)
