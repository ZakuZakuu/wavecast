from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from wavecast.arrangement.models import AudioClip, GainPoint, MixPlan
from wavecast.models.episode import PlayableEpisode, Segment, SegmentKind


@dataclass(frozen=True)
class ArrangementDefaults:
    """Small bounded defaults for a radio-like baseline, not a DAW."""

    outgoing_voice_overlap_seconds: float = 1.0
    crossfade_seconds: float = 3.0
    music_fade_in_seconds: float = 3.0
    music_fade_out_seconds: float = 3.0
    voice_fade_seconds: float = 0.08
    duck_gain: float = 0.35
    duck_attack_seconds: float = 0.5
    duck_release_seconds: float = 0.5


def _active_segments(episode: PlayableEpisode) -> list[Segment]:
    segments = [segment for segment in episode.segments if segment.is_timeline_active]
    if not segments:
        raise ValueError("cannot arrange an episode with no active segments")
    for segment in segments:
        if not segment.is_audio_ready:
            raise ValueError(f"segment is not audio-ready: {segment.id}")
        if not segment.audio_source_url:
            raise ValueError(f"audio-ready segment has no source URL: {segment.id}")
    return sorted(segments, key=lambda segment: segment.order)


def _duration(segment: Segment) -> float:
    return float(segment.duration_seconds)


def _music_before(segments: list[Segment], index: int) -> int | None:
    for candidate in range(index - 1, -1, -1):
        if segments[candidate].kind is SegmentKind.MUSIC:
            return candidate
    return None


def _music_after(segments: list[Segment], index: int) -> int | None:
    for candidate in range(index + 1, len(segments)):
        if segments[candidate].kind is SegmentKind.MUSIC:
            return candidate
    return None


def _unique_points(points: Iterable[GainPoint]) -> tuple[GainPoint, ...]:
    by_offset: dict[float, GainPoint] = {}
    for point in points:
        by_offset[round(point.offset_seconds, 6)] = point
    return tuple(by_offset[offset] for offset in sorted(by_offset))


def _fade_factor(offset: float, duration: float, fade_in: float, fade_out: float) -> float:
    if fade_in and offset < fade_in:
        return max(0.0, min(1.0, offset / fade_in))
    if fade_out and offset > duration - fade_out:
        return max(0.0, min(1.0, (duration - offset) / fade_out))
    return 1.0


def _music_automation(
    *,
    start: float,
    duration: float,
    fade_in: float,
    fade_out: float,
    narration_intervals: list[tuple[float, float]],
    duck_gain: float,
    duck_attack: float,
    duck_release: float,
) -> tuple[GainPoint, ...]:
    offsets = {0.0, duration}
    if fade_in:
        offsets.add(min(duration, fade_in))
    if fade_out:
        offsets.add(max(0.0, duration - fade_out))
    for narration_start, narration_end in narration_intervals:
        if narration_end > start and narration_start < start + duration:
            offsets.update(
                {
                    max(0.0, narration_start - duck_attack - start),
                    max(0.0, narration_start - start),
                    min(duration, narration_end - start),
                    min(duration, narration_end + duck_release - start),
                }
            )

    def duck_factor(absolute: float) -> float:
        factor = 1.0
        for narration_start, narration_end in narration_intervals:
            if narration_start - duck_attack < absolute < narration_start:
                progress = (absolute - (narration_start - duck_attack)) / duck_attack
                factor = min(factor, 1.0 + (duck_gain - 1.0) * progress)
            elif narration_start <= absolute < narration_end:
                factor = min(factor, duck_gain)
            elif narration_end <= absolute < narration_end + duck_release:
                progress = (absolute - narration_end) / duck_release
                factor = min(factor, duck_gain + (1.0 - duck_gain) * progress)
        return factor

    points: list[GainPoint] = []
    for offset in sorted(offsets):
        absolute = start + offset
        points.append(
            GainPoint(
                offset_seconds=offset,
                gain=_fade_factor(offset, duration, fade_in, fade_out)
                * duck_factor(absolute),
            )
        )
    return _unique_points(points)


def plan_episode_mix(
    episode: PlayableEpisode,
    defaults: ArrangementDefaults | None = None,
) -> MixPlan:
    """Build a deterministic overlap arrangement from a materialized timeline."""

    config = defaults or ArrangementDefaults()
    segments = _active_segments(episode)
    starts: dict[str, float] = {}
    starts_by_index: dict[int, float] = {}
    cursor = 0.0

    for index, segment in enumerate(segments):
        duration = _duration(segment)
        previous = segments[index - 1] if index else None
        if index == 0:
            start = 0.0
        elif segment.kind is SegmentKind.MUSIC:
            prior_music_index = _music_before(segments, index)
            if prior_music_index is not None:
                prior_start = starts_by_index[prior_music_index]
                prior_end = prior_start + _duration(segments[prior_music_index])
                start = max(0.0, prior_end - config.crossfade_seconds)
            else:
                start = cursor
        elif previous and previous.kind is SegmentKind.MUSIC:
            previous_end = starts_by_index[index - 1] + _duration(previous)
            start = max(
                0.0,
                previous_end
                - min(config.outgoing_voice_overlap_seconds, _duration(previous)),
            )
        else:
            start = cursor

        starts_by_index[index] = start
        starts[segment.id] = start
        cursor = max(cursor, start + duration)

    narration_intervals = [
        (starts_by_index[index], starts_by_index[index] + _duration(segment))
        for index, segment in enumerate(segments)
        if segment.kind is SegmentKind.NARRATION
    ]

    clips: list[AudioClip] = []
    for index, segment in enumerate(segments):
        start = starts_by_index[index]
        duration = _duration(segment)
        if segment.kind is SegmentKind.NARRATION:
            clips.append(
                AudioClip(
                    id=f"{segment.id}:voice",
                    segment_id=segment.id,
                    source_url=segment.audio_source_url or "",
                    lane="VOICE",
                    timeline_start_seconds=start,
                    source_offset_seconds=0,
                    playable_duration_seconds=duration,
                    gain_automation=(
                        GainPoint(offset_seconds=0, gain=0),
                        GainPoint(offset_seconds=min(config.voice_fade_seconds, duration), gain=1),
                        GainPoint(
                            offset_seconds=max(0, duration - config.voice_fade_seconds), gain=1
                        ),
                        GainPoint(offset_seconds=duration, gain=0),
                    ),
                )
            )
            continue

        previous_music = _music_before(segments, index) is not None
        next_music = _music_after(segments, index)
        fade_in = config.music_fade_in_seconds if previous_music else 0.0
        fade_out = config.music_fade_out_seconds if next_music is not None else 0.0
        clips.append(
            AudioClip(
                id=f"{segment.id}:music",
                segment_id=segment.id,
                source_url=segment.audio_source_url or "",
                lane="MUSIC",
                timeline_start_seconds=start,
                source_offset_seconds=0,
                playable_duration_seconds=duration,
                fade_in_seconds=min(fade_in, duration),
                fade_out_seconds=min(fade_out, duration),
                gain_automation=_music_automation(
                    start=start,
                    duration=duration,
                    fade_in=min(fade_in, duration),
                    fade_out=min(fade_out, duration),
                    narration_intervals=narration_intervals,
                    duck_gain=config.duck_gain,
                    duck_attack=config.duck_attack_seconds,
                    duck_release=config.duck_release_seconds,
                ),
            )
        )

    duration = max(clip.timeline_end_seconds for clip in clips)
    return MixPlan(
        episode_id=episode.id,
        duration_seconds=duration,
        clips=tuple(clips),
        segment_starts=starts,
    )
