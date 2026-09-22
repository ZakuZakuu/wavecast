from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MixLane = Literal["MUSIC", "VOICE"]


class GainPoint(BaseModel):
    """A deterministic gain value at a clip-local timeline offset."""

    model_config = ConfigDict(frozen=True)

    offset_seconds: float = Field(ge=0, serialization_alias="offsetSeconds")
    gain: float = Field(ge=0, le=1)


class AudioClip(BaseModel):
    """One source clip in the final listener-facing arrangement."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    segment_id: str = Field(min_length=1, serialization_alias="segmentId")
    source_url: str = Field(min_length=1, serialization_alias="sourceUrl")
    lane: MixLane
    timeline_start_seconds: float = Field(ge=0, serialization_alias="timelineStartSeconds")
    source_offset_seconds: float = Field(ge=0, serialization_alias="sourceOffsetSeconds")
    playable_duration_seconds: float = Field(gt=0, serialization_alias="playableDurationSeconds")
    gain: float = Field(ge=0, le=1, default=1)
    fade_in_seconds: float = Field(ge=0, default=0, serialization_alias="fadeInSeconds")
    fade_out_seconds: float = Field(ge=0, default=0, serialization_alias="fadeOutSeconds")
    gain_automation: tuple[GainPoint, ...] = Field(default=(), serialization_alias="gainAutomation")

    @model_validator(mode="after")
    def validate_timing(self) -> AudioClip:
        if self.fade_in_seconds > self.playable_duration_seconds:
            raise ValueError("fade_in_seconds cannot exceed playable duration")
        if self.fade_out_seconds > self.playable_duration_seconds:
            raise ValueError("fade_out_seconds cannot exceed playable duration")
        previous = -1.0
        for point in self.gain_automation:
            if point.offset_seconds > self.playable_duration_seconds:
                raise ValueError("gain automation cannot exceed playable duration")
            if point.offset_seconds < previous:
                raise ValueError("gain automation points must be ordered")
            previous = point.offset_seconds
        return self

    @property
    def timeline_end_seconds(self) -> float:
        return self.timeline_start_seconds + self.playable_duration_seconds


class MixPlan(BaseModel):
    """Typed, serializable arrangement consumed by realtime/offline renderers."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = Field(default=1, serialization_alias="schemaVersion")
    episode_id: str = Field(min_length=1, serialization_alias="episodeId")
    duration_seconds: float = Field(gt=0, serialization_alias="durationSeconds")
    clips: tuple[AudioClip, ...] = Field(min_length=1)
    segment_starts: dict[str, float] = Field(default_factory=dict, serialization_alias="segmentStarts")

    @model_validator(mode="after")
    def validate_clips(self) -> MixPlan:
        clip_ids: set[str] = set()
        for clip in self.clips:
            if clip.id in clip_ids:
                raise ValueError("mix clip ids must be unique")
            if clip.timeline_end_seconds > self.duration_seconds + 1e-6:
                raise ValueError("mix clip cannot extend beyond plan duration")
            clip_ids.add(clip.id)
        for segment_id, start in self.segment_starts.items():
            if start < 0 or start > self.duration_seconds:
                raise ValueError(f"segment start is outside plan: {segment_id}")
        return self
