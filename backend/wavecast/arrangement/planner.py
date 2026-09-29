from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from wavecast.arrangement.models import AudioClip, GainPoint, MixPlan
from wavecast.audio_timing import (
    TrackSectionKind,
    TrackTimingProfile,
    safe_incoming_music_overlap_seconds,
    safe_outgoing_narration_overlap_seconds,
)
from wavecast.models.episode import (
    MusicSegment,
    NarrationRole,
    PlayableEpisode,
    Segment,
    SegmentKind,
)


@dataclass(frozen=True)
class ArrangementDefaults:
    """Deterministic first-pass radio mixing primitives.

    The three baseline behaviors are intentionally independent:
    direct music-to-music uses a long crossfade, narration between tracks uses
    a narrated bridge envelope, and narration without a track handoff only
    ducks the music underneath the voice.
    """

    outgoing_voice_overlap_seconds: float = 5.0
    crossfade_seconds: float = 10.0
    incoming_narration_offset_seconds: float = 1.0
    bridge_incoming_fade_seconds: float = 5.0
    music_fade_in_seconds: float = 10.0
    music_fade_out_seconds: float = 10.0
    voice_fade_seconds: float = 0.08
    duck_gain: float = 0.30
    duck_attack_seconds: float = 1.5
    duck_release_seconds: float = 1.5
    lyric_aware_outgoing_overlap_seconds: float = 12.0
    lyric_guard_seconds: float = 0.75
    opening_host_lead_in_seconds: float = 6.0


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


def _narration_role(segment: Segment) -> NarrationRole:
    return getattr(segment, "narration_role", NarrationRole.GENERAL)


def _timing_profile(segment: Segment) -> TrackTimingProfile | None:
    return segment.timing_profile if isinstance(segment, MusicSegment) else None


def _is_opening_host_overlay(segment: Segment) -> bool:
    # This is the single preliminary-round opening host beat prepared before
    # playback. Keep the special case narrow so historical Writer INTRO blocks
    # retain their existing bridge semantics.
    return (
        segment.kind is SegmentKind.NARRATION
        and segment.id == "segment-opening-host"
    )


def _only_opening_overlay_between(
    segments: list[Segment],
    left_index: int,
    right_index: int,
) -> bool:
    between = segments[left_index + 1 : right_index]
    return bool(between) and all(_is_opening_host_overlay(item) for item in between)


def _opening_host_offset_seconds(
    music: Segment,
    narration_duration: float,
    config: ArrangementDefaults,
) -> float | None:
    profile = _timing_profile(music)
    if profile is None:
        # Preliminary radio fallback: an opening host should stay an opening.
        # If timing metadata is unavailable, prefer one short early talk-over
        # rather than semantically moving an introduction to the song tail.
        return config.opening_host_lead_in_seconds

    preferred_kinds = (
        TrackSectionKind.INTRO_INSTRUMENTAL,
        TrackSectionKind.INSTRUMENTAL_GAP,
    )
    for kind in preferred_kinds:
        for section in profile.sections:
            if section.kind is not kind:
                continue
            earliest = max(
                config.opening_host_lead_in_seconds,
                section.start_seconds + config.lyric_guard_seconds,
            )
            latest_start = (
                section.end_seconds
                - config.lyric_guard_seconds
                - narration_duration
            )
            if earliest <= latest_start:
                return earliest
    # Timing exists but exposes no sufficiently long non-vocal section.
    # Keep the opening beat early rather than falling through to the generic
    # outgoing-song bridge placement at the end of the track.
    return config.opening_host_lead_in_seconds


def _incoming_voice_overlap_seconds(
    segment: Segment,
    config: ArrangementDefaults,
) -> float:
    return safe_incoming_music_overlap_seconds(
        _timing_profile(segment),
        fallback_seconds=config.bridge_incoming_fade_seconds,
        guard_seconds=config.lyric_guard_seconds,
    )


def _narration_run_before(segments: list[Segment], index: int) -> list[int]:
    run: list[int] = []
    candidate = index - 1
    while candidate >= 0 and segments[candidate].kind is SegmentKind.NARRATION:
        run.append(candidate)
        candidate -= 1
    run.reverse()
    return run


def _narration_run_after(segments: list[Segment], index: int) -> list[int]:
    run: list[int] = []
    candidate = index + 1
    while candidate < len(segments) and segments[candidate].kind is SegmentKind.NARRATION:
        run.append(candidate)
        candidate += 1
    return run


def _bridge_run_before(segments: list[Segment], index: int) -> list[int]:
    run = _narration_run_before(segments, index)
    if not run or any(_is_opening_host_overlay(segments[item]) for item in run):
        return []
    previous_index = run[0] - 1
    if previous_index >= 0 and segments[previous_index].kind is SegmentKind.MUSIC:
        return run
    return []


def _bridge_run_after(segments: list[Segment], index: int) -> list[int]:
    run = _narration_run_after(segments, index)
    if not run or any(_is_opening_host_overlay(segments[item]) for item in run):
        return []
    next_index = run[-1] + 1
    if next_index < len(segments) and segments[next_index].kind is SegmentKind.MUSIC:
        return run
    return []


def _semantic_incoming_music_start(
    *,
    segments: list[Segment],
    index: int,
    starts_by_index: dict[int, float],
    config: ArrangementDefaults,
    fallback: float,
    timing_profile: TrackTimingProfile | None,
) -> float:
    """Placement for narration that is not bridging out of a previous song."""

    run = _narration_run_before(segments, index)
    if not run:
        return fallback

    track_intro_index = next(
        (
            candidate
            for candidate in reversed(run)
            if _narration_role(segments[candidate]) is NarrationRole.TRACK_INTRO
        ),
        None,
    )
    if track_intro_index is not None:
        narration_start = starts_by_index[track_intro_index]
        narration_end = narration_start + _duration(segments[track_intro_index])
        allowed_overlap = safe_incoming_music_overlap_seconds(
            timing_profile,
            fallback_seconds=max(0.0, narration_end - narration_start),
            guard_seconds=config.lyric_guard_seconds,
        )
        return max(narration_start, narration_end - allowed_overlap)

    if any(
        _narration_role(segments[candidate])
        in {NarrationRole.TRANSITION, NarrationRole.INTRO}
        for candidate in run
    ):
        last = run[-1]
        duration = _duration(segments[last])
        narration_start = starts_by_index[last]
        narration_end = narration_start + duration
        fallback_overlap = max(
            0.0,
            duration - min(config.incoming_narration_offset_seconds, duration / 2),
        )
        allowed_overlap = safe_incoming_music_overlap_seconds(
            timing_profile,
            fallback_seconds=fallback_overlap,
            guard_seconds=config.lyric_guard_seconds,
        )
        return max(narration_start, narration_end - allowed_overlap)

    return fallback


def _unique_points(points: Iterable[GainPoint]) -> tuple[GainPoint, ...]:
    by_offset: dict[float, GainPoint] = {}
    for point in points:
        by_offset[round(point.offset_seconds, 6)] = point
    return tuple(by_offset[offset] for offset in sorted(by_offset))


def _lerp(left: float, right: float, progress: float) -> float:
    bounded = max(0.0, min(1.0, progress))
    return left + (right - left) * bounded


def _fade_factor(offset: float, duration: float, fade_in: float, fade_out: float) -> float:
    factor = 1.0
    if fade_in:
        factor = min(factor, max(0.0, min(1.0, offset / fade_in)))
    if fade_out:
        factor = min(
            factor,
            max(0.0, min(1.0, (duration - offset) / fade_out)),
        )
    return factor


def _duck_factor(
    absolute: float,
    *,
    intervals: list[tuple[float, float]],
    duck_gain: float,
    duck_attack: float,
    duck_release: float,
) -> float:
    factor = 1.0
    for narration_start, narration_end in intervals:
        if duck_attack > 0 and narration_start - duck_attack < absolute < narration_start:
            progress = (absolute - (narration_start - duck_attack)) / duck_attack
            factor = min(factor, _lerp(1.0, duck_gain, progress))
        elif narration_start <= absolute < narration_end:
            factor = min(factor, duck_gain)
        elif duck_release > 0 and narration_end <= absolute < narration_end + duck_release:
            progress = (absolute - narration_end) / duck_release
            factor = min(factor, _lerp(duck_gain, 1.0, progress))
    return factor


def _bridge_outgoing_factor(
    absolute: float,
    *,
    narration_start: float,
    music_end: float,
    duck_gain: float,
    duck_attack: float,
) -> float:
    attack_start = narration_start - duck_attack
    if absolute <= attack_start:
        return 1.0
    if absolute < narration_start and duck_attack > 0:
        return _lerp(
            1.0,
            duck_gain,
            (absolute - attack_start) / duck_attack,
        )
    if absolute < music_end:
        span = music_end - narration_start
        if span <= 0:
            return 0.0
        return _lerp(
            duck_gain,
            0.0,
            (absolute - narration_start) / span,
        )
    return 0.0


def _bridge_incoming_factor(
    absolute: float,
    *,
    music_start: float,
    narration_end: float,
    fade_seconds: float,
    duck_gain: float,
    duck_release: float,
) -> float:
    if absolute <= music_start:
        return 0.0

    if narration_end <= music_start:
        if fade_seconds <= 0:
            return 1.0
        return _lerp(
            0.0,
            1.0,
            (absolute - music_start) / fade_seconds,
        )

    ramp_end = min(narration_end, music_start + fade_seconds)
    if absolute < ramp_end:
        span = ramp_end - music_start
        if span <= 0:
            return duck_gain
        return _lerp(
            0.0,
            duck_gain,
            (absolute - music_start) / span,
        )
    if absolute < narration_end:
        return duck_gain
    if duck_release > 0 and absolute < narration_end + duck_release:
        return _lerp(
            duck_gain,
            1.0,
            (absolute - narration_end) / duck_release,
        )
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
    outgoing_bridge: tuple[float, float] | None = None,
    incoming_bridge: tuple[float, float] | None = None,
    bridge_incoming_fade: float = 0.0,
) -> tuple[GainPoint, ...]:
    offsets = {0.0, duration}
    end = start + duration

    if fade_in:
        offsets.add(min(duration, fade_in))
    if fade_out:
        offsets.add(max(0.0, duration - fade_out))

    for narration_start, narration_end in narration_intervals:
        if narration_end > start and narration_start < end:
            offsets.update(
                {
                    max(0.0, narration_start - duck_attack - start),
                    max(0.0, narration_start - start),
                    min(duration, narration_end - start),
                    min(duration, narration_end + duck_release - start),
                }
            )

    if outgoing_bridge is not None:
        narration_start, _ = outgoing_bridge
        offsets.update(
            {
                max(0.0, narration_start - duck_attack - start),
                max(0.0, narration_start - start),
                duration,
            }
        )

    if incoming_bridge is not None:
        _, narration_end = incoming_bridge
        ramp_end = min(narration_end, start + bridge_incoming_fade)
        offsets.update(
            {
                0.0,
                max(0.0, min(duration, ramp_end - start)),
                max(0.0, min(duration, narration_end - start)),
                max(0.0, min(duration, narration_end + duck_release - start)),
            }
        )

    points: list[GainPoint] = []
    for offset in sorted(offsets):
        absolute = start + offset
        gain = _fade_factor(offset, duration, fade_in, fade_out)
        gain *= _duck_factor(
            absolute,
            intervals=narration_intervals,
            duck_gain=duck_gain,
            duck_attack=duck_attack,
            duck_release=duck_release,
        )
        if outgoing_bridge is not None:
            gain *= _bridge_outgoing_factor(
                absolute,
                narration_start=outgoing_bridge[0],
                music_end=end,
                duck_gain=duck_gain,
                duck_attack=duck_attack,
            )
        if incoming_bridge is not None:
            gain *= _bridge_incoming_factor(
                absolute,
                music_start=start,
                narration_end=incoming_bridge[1],
                fade_seconds=bridge_incoming_fade,
                duck_gain=duck_gain,
                duck_release=duck_release,
            )
        points.append(
            GainPoint(
                offset_seconds=offset,
                gain=max(0.0, min(1.0, gain)),
            )
        )
    return _unique_points(points)


def _run_interval(
    run: list[int],
    *,
    segments: list[Segment],
    starts_by_index: dict[int, float],
) -> tuple[float, float] | None:
    if not run:
        return None
    first = run[0]
    last = run[-1]
    return (
        starts_by_index[first],
        starts_by_index[last] + _duration(segments[last]),
    )


def plan_episode_mix(
    episode: PlayableEpisode,
    defaults: ArrangementDefaults | None = None,
) -> MixPlan:
    """Build deterministic radio-style mixing from one ready timeline prefix."""

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
            bridge_run = _bridge_run_before(segments, index)
            prior_music_index = _music_before(segments, index)

            if bridge_run and prior_music_index is not None:
                prior_start = starts_by_index[prior_music_index]
                prior_end = prior_start + _duration(segments[prior_music_index])
                narration_end = (
                    starts_by_index[bridge_run[-1]]
                    + _duration(segments[bridge_run[-1]])
                )
                allowed_incoming_overlap = _incoming_voice_overlap_seconds(
                    segment,
                    config,
                )
                start = max(
                    prior_end,
                    narration_end - allowed_incoming_overlap,
                )
            elif previous and previous.kind is SegmentKind.MUSIC:
                previous_start = starts_by_index[index - 1]
                previous_duration = _duration(previous)
                overlap = min(
                    config.crossfade_seconds,
                    previous_duration,
                    duration,
                )
                start = max(0.0, previous_start + previous_duration - overlap)
            elif (
                prior_music_index is not None
                and _only_opening_overlay_between(
                    segments,
                    prior_music_index,
                    index,
                )
            ):
                prior_start = starts_by_index[prior_music_index]
                prior_duration = _duration(segments[prior_music_index])
                overlap = min(
                    config.crossfade_seconds,
                    prior_duration,
                    duration,
                )
                start = max(0.0, prior_start + prior_duration - overlap)
            elif previous and previous.kind is SegmentKind.NARRATION:
                start = _semantic_incoming_music_start(
                    segments=segments,
                    index=index,
                    starts_by_index=starts_by_index,
                    config=config,
                    fallback=cursor,
                    timing_profile=_timing_profile(segment),
                )
            else:
                start = cursor
        elif previous and previous.kind is SegmentKind.MUSIC:
            previous_end = starts_by_index[index - 1] + _duration(previous)
            opening_offset = (
                _opening_host_offset_seconds(previous, duration, config)
                if _is_opening_host_overlay(segment)
                else None
            )
            if opening_offset is not None:
                start = starts_by_index[index - 1] + opening_offset
                starts_by_index[index] = start
                starts[segment.id] = start
                cursor = max(cursor, start + duration)
                continue
            fallback_overlap = min(
                config.outgoing_voice_overlap_seconds,
                duration / 2,
                _duration(previous),
            )
            timing_profile = _timing_profile(previous)
            if timing_profile is None:
                overlap = fallback_overlap
            else:
                overlap = safe_outgoing_narration_overlap_seconds(
                    timing_profile,
                    fallback_seconds=fallback_overlap,
                    max_seconds=min(
                        config.lyric_aware_outgoing_overlap_seconds,
                        duration,
                        _duration(previous),
                    ),
                    guard_seconds=config.lyric_guard_seconds,
                )
            start = max(0.0, previous_end - overlap)
        else:
            start = cursor

        starts_by_index[index] = start
        starts[segment.id] = start
        cursor = max(cursor, start + duration)

    narration_by_index = {
        index: (
            starts_by_index[index],
            starts_by_index[index] + _duration(segment),
        )
        for index, segment in enumerate(segments)
        if segment.kind is SegmentKind.NARRATION
    }

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
                    fade_in_seconds=min(config.voice_fade_seconds, duration),
                    fade_out_seconds=min(config.voice_fade_seconds, duration),
                    gain_automation=(
                        GainPoint(offset_seconds=0, gain=0),
                        GainPoint(
                            offset_seconds=min(config.voice_fade_seconds, duration),
                            gain=1,
                        ),
                        GainPoint(
                            offset_seconds=max(
                                0,
                                duration - config.voice_fade_seconds,
                            ),
                            gain=1,
                        ),
                        GainPoint(offset_seconds=duration, gain=0),
                    ),
                )
            )
            continue

        incoming_run = _bridge_run_before(segments, index)
        outgoing_run = _bridge_run_after(segments, index)
        incoming_bridge = _run_interval(
            incoming_run,
            segments=segments,
            starts_by_index=starts_by_index,
        )
        outgoing_bridge = _run_interval(
            outgoing_run,
            segments=segments,
            starts_by_index=starts_by_index,
        )

        previous_music_index = _music_before(segments, index)
        next_music_index = _music_after(segments, index)
        previous_is_music = bool(
            previous_music_index is not None
            and (
                previous_music_index == index - 1
                or _only_opening_overlay_between(
                    segments,
                    previous_music_index,
                    index,
                )
            )
        )
        next_is_music = bool(
            next_music_index is not None
            and (
                next_music_index == index + 1
                or _only_opening_overlay_between(
                    segments,
                    index,
                    next_music_index,
                )
            )
        )

        fade_in = (
            min(config.music_fade_in_seconds, duration)
            if previous_is_music
            else 0.0
        )
        fade_out = (
            min(config.music_fade_out_seconds, duration)
            if next_is_music
            else 0.0
        )

        excluded_narration = set(incoming_run) | set(outgoing_run)
        duck_intervals = [
            interval
            for narration_index, interval in narration_by_index.items()
            if narration_index not in excluded_narration
        ]

        bridge_incoming_fade = _incoming_voice_overlap_seconds(segment, config)

        metadata_fade_in = fade_in
        if incoming_bridge is not None:
            metadata_fade_in = min(
                duration,
                bridge_incoming_fade,
                max(0.0, incoming_bridge[1] - start),
            )

        metadata_fade_out = fade_out
        if outgoing_bridge is not None:
            metadata_fade_out = min(
                duration,
                max(0.0, start + duration - outgoing_bridge[0]),
            )

        clips.append(
            AudioClip(
                id=f"{segment.id}:music",
                segment_id=segment.id,
                source_url=segment.audio_source_url or "",
                lane="MUSIC",
                timeline_start_seconds=start,
                source_offset_seconds=0,
                playable_duration_seconds=duration,
                fade_in_seconds=metadata_fade_in,
                fade_out_seconds=metadata_fade_out,
                gain_automation=_music_automation(
                    start=start,
                    duration=duration,
                    fade_in=fade_in,
                    fade_out=fade_out,
                    narration_intervals=duck_intervals,
                    duck_gain=config.duck_gain,
                    duck_attack=config.duck_attack_seconds,
                    duck_release=config.duck_release_seconds,
                    outgoing_bridge=outgoing_bridge,
                    incoming_bridge=incoming_bridge,
                    bridge_incoming_fade=bridge_incoming_fade,
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
