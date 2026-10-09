from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from wavecast.audio_timing import TrackTimingProfile
from wavecast.language import OutputLanguage
from wavecast.presentation import PresentationIntent
from wavecast.stations import StationId


def utc_now() -> datetime:
    return datetime.now(UTC)


class EpisodeState(StrEnum):
    SEED = "SEED"
    STARTED = "STARTED"
    RESEARCHING = "RESEARCHING"
    PLANNED = "PLANNED"
    STREAMING = "STREAMING"
    MATERIALIZING = "MATERIALIZING"
    MATERIALIZED = "MATERIALIZED"
    PUBLISHED = "PUBLISHED"
    CANCELLED = "CANCELLED"


class GenerationMode(StrEnum):
    PROGRESSIVE = "PROGRESSIVE"
    FULL = "FULL"


class SegmentKind(StrEnum):
    MUSIC = "MUSIC"
    NARRATION = "NARRATION"


class NarrationRole(StrEnum):
    """Provider-neutral semantic role for one spoken timeline segment."""

    INTRO = "INTRO"
    TRACK_INTRO = "TRACK_INTRO"
    TRANSITION = "TRANSITION"
    OUTRO = "OUTRO"
    GENERAL = "GENERAL"


class SegmentState(StrEnum):
    PLANNED = "PLANNED"
    SCRIPT_READY = "SCRIPT_READY"
    AUDIO_GENERATING = "AUDIO_GENERATING"
    AUDIO_READY = "AUDIO_READY"
    COMMITTED = "COMMITTED"
    PLAYED = "PLAYED"
    SKIPPED = "SKIPPED"


class CoverParams(BaseModel):
    model_config = ConfigDict(frozen=True)

    family: str
    seed: int
    palette: tuple[str, str]


class EpisodeSeed(BaseModel):
    id: str
    title: str
    topic: str
    short_description: str
    estimated_duration_seconds: int = Field(gt=0)
    opening_track_ref: str
    opening_track_title: str
    opening_track_artist: str
    opening_track_duration_seconds: int | None = Field(default=None, gt=0)
    opening_track_timing_profile: TrackTimingProfile | None = None
    opening_narration_text: str | None = Field(default=None, max_length=320)
    cover: CoverParams
    presentation_intent: PresentationIntent = Field(default_factory=PresentationIntent)
    output_language: OutputLanguage = OutputLanguage.AUTO
    station: StationId | None = None
    generation_profile: str = "balanced"
    created_at: datetime = Field(default_factory=utc_now)


class Segment(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    chapter_id: str
    order: int = Field(ge=0)
    kind: SegmentKind
    state: SegmentState = SegmentState.PLANNED
    planned_duration_seconds: int = Field(gt=0)
    actual_duration_seconds: int | None = Field(default=None, gt=0)
    track_ref: str | None = None
    audio_source_url: str | None = None
    title: str
    artist: str | None = None
    narration_text: str | None = None
    asset_ref: str | None = None
    committed_at: datetime | None = None
    played_at: datetime | None = None

    @model_validator(mode="after")
    def validate_kind_fields(self) -> Segment:
        if self.kind is SegmentKind.MUSIC and self.track_ref is None:
            raise ValueError("music segments require a track_ref")
        if self.kind is SegmentKind.NARRATION and self.track_ref is not None:
            raise ValueError("narration segments cannot have a track_ref")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def duration_seconds(self) -> int:
        return self.actual_duration_seconds or self.planned_duration_seconds

    @property
    def is_audio_ready(self) -> bool:
        return self.state in {SegmentState.AUDIO_READY, SegmentState.COMMITTED, SegmentState.PLAYED}

    @property
    def is_committed(self) -> bool:
        return self.state in {SegmentState.COMMITTED, SegmentState.PLAYED}

    @property
    def is_timeline_active(self) -> bool:
        return self.state is not SegmentState.SKIPPED


class MusicSegment(Segment):
    """A timeline segment backed by a playable music source."""

    kind: Literal[SegmentKind.MUSIC] = SegmentKind.MUSIC
    track_ref: str
    audio_source_url: str | None = None
    timing_profile: TrackTimingProfile | None = None


class NarrationSegment(Segment):
    """A timeline segment backed by generated or mock narration audio."""

    kind: Literal[SegmentKind.NARRATION] = SegmentKind.NARRATION
    audio_source_url: str | None = None
    # ``narration_text`` remains the visible/editorial copy.  ``tts_text`` is
    # an optional pronunciation-aware rendering supplied by the Writer.
    tts_text: str | None = Field(default=None, min_length=1)
    tts_cues: list[str] = Field(default_factory=list)
    narration_role: NarrationRole = NarrationRole.GENERAL


class PlayableEpisode(BaseModel):
    """A deterministic composed timeline ready for browser runtime ingestion."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    segments: list[MusicSegment | NarrationSegment]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def duration_seconds(self) -> int:
        return sum(
            segment.duration_seconds for segment in self.segments if segment.is_timeline_active
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def timeline_duration_seconds(self) -> int:
        return self.duration_seconds


class LiveEpisode(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    seed_id: str
    title: str | None = None
    topic: str | None = None
    listener_id: str = "test-listener"
    # Account ownership is separate from immutable runtime listener identity.
    owner_user_id: str | None = Field(default=None, exclude=True)
    version: int = Field(default=0, ge=0)
    state: EpisodeState = EpisodeState.STARTED
    generation_mode: GenerationMode = GenerationMode.PROGRESSIVE
    program_estimated_duration_seconds: int = Field(gt=0)
    presentation_intent: PresentationIntent = Field(default_factory=PresentationIntent)
    output_language: OutputLanguage = OutputLanguage.AUTO
    station: StationId | None = None
    progressive_session: ProgressiveAssemblySession | None = Field(
        default=None, exclude=True, repr=False
    )
    segments: list[MusicSegment | NarrationSegment]
    current_segment_id: str | None = None
    playback_position_seconds: int = Field(default=0, ge=0)
    # Single-source programme playback owns a separate cursor. It is listener
    # scheduling metadata only: updating it must never commit/skip/reorder
    # segments or rewrite the immutable rendered programme.
    program_playback_position_seconds: float = Field(default=0, ge=0)
    program_transport_active: bool = False
    program_rendered_frontier_seconds: float | None = Field(default=None, ge=0)
    program_publication_latency_seconds: float = Field(default=0, ge=0, le=600)
    generation_latency_seconds: float = Field(default=0, ge=0, le=600)
    is_listener_active: bool = True
    is_playing: bool = True
    last_activity_at: datetime = Field(default_factory=utc_now)
    last_heartbeat_at: datetime = Field(default_factory=utc_now)
    created_at: datetime = Field(default_factory=utc_now)

    @property
    def ordered_segments(self) -> list[Segment]:
        return sorted(self.segments, key=lambda segment: segment.order)

    @property
    def timeline_segments(self) -> list[Segment]:
        return [segment for segment in self.ordered_segments if segment.is_timeline_active]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def generated_frontier_seconds(self) -> int:
        total = 0
        for segment in self.timeline_segments:
            if not segment.is_audio_ready:
                break
            total += segment.duration_seconds
        return total

    @computed_field  # type: ignore[prop-decorator]
    @property
    def buffer_ahead_seconds(self) -> int:
        """Return contiguous generated audio ahead of the active listener cursor."""
        position = (
            self.program_playback_position_seconds
            if self.program_transport_active
            else self.playback_position_seconds
        )
        return max(0, int(self.generated_frontier_seconds - position))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def ready_audio_seconds_ahead(self) -> int:
        """Return playable audio ahead for the active transport.

        The immutable programme transport deliberately uses its own cursor and
        does not mutate lifecycle segment identity. Its conservative generated
        frontier stops at unfinished transition inputs, which is exactly the
        boundary the server-side renderer may safely publish.
        """
        if self.program_transport_active:
            return max(
                0,
                int(
                    self.generated_frontier_seconds
                    - self.program_playback_position_seconds
                ),
            )
        if self.current_segment_id is None:
            return 0
        try:
            current_index = next(
                index
                for index, segment in enumerate(self.timeline_segments)
                if segment.id == self.current_segment_id
            )
        except StopIteration:
            return 0

        current = self.timeline_segments[current_index]
        if not current.is_audio_ready:
            return 0

        current_start = sum(
            segment.duration_seconds
            for segment in self.timeline_segments[:current_index]
        )
        played_in_current = max(0, self.playback_position_seconds - current_start)
        ready_seconds = max(0, current.duration_seconds - played_in_current)

        for segment in self.timeline_segments[current_index + 1 :]:
            if segment.is_audio_ready:
                ready_seconds += segment.duration_seconds
                continue
            if segment.kind is SegmentKind.NARRATION:
                continue
            break
        return ready_seconds

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_ready_successor(self) -> bool:
        """Whether playback can reach another ready music source without waiting."""
        if self.current_segment_id is None:
            return False
        seen_current = False
        for segment in self.timeline_segments:
            if not seen_current:
                seen_current = segment.id == self.current_segment_id
                continue
            if segment.kind is SegmentKind.NARRATION:
                continue
            if segment.kind is SegmentKind.MUSIC:
                return segment.is_audio_ready
        return False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def committed_frontier_seconds(self) -> int:
        total = 0
        for segment in self.timeline_segments:
            if not segment.is_committed:
                break
            total += segment.duration_seconds
        return total

    @computed_field  # type: ignore[prop-decorator]
    @property
    def timeline_duration_seconds(self) -> int:
        return sum(segment.duration_seconds for segment in self.timeline_segments)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def estimated_total_seconds(self) -> int:
        """Deprecated compatibility alias for the current, not promised, timeline."""
        return self.timeline_duration_seconds

    def segment(self, segment_id: str) -> Segment:
        for segment in self.segments:
            if segment.id == segment_id:
                return segment
        raise KeyError(f"unknown segment: {segment_id}")


# Deferred to the end of this module so the low-level durable contract can import
# intelligence models without observing a partially initialized Episode model.
from wavecast.models.progressive import ProgressiveAssemblySession  # noqa: E402

LiveEpisode.model_rebuild()
