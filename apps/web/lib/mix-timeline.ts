import type { LiveEpisode, Segment } from "./types";

export type MixLane = "MUSIC" | "VOICE";

export type GainPoint = {
  offsetSeconds: number;
  gain: number;
};

export type MixClip = {
  id: string;
  segmentId: string;
  sourceUrl: string;
  lane: MixLane;
  timelineStartSeconds: number;
  sourceOffsetSeconds: number;
  playableDurationSeconds: number;
  gain: number;
  fadeInSeconds: number;
  fadeOutSeconds: number;
  gainAutomation: GainPoint[];
};

export type MixPlan = {
  episodeId: string;
  durationSeconds: number;
  clips: MixClip[];
  segmentStarts: Record<string, number>;
};

export const MIX_DEFAULTS = {
  outgoingVoiceOverlapSeconds: 1,
  crossfadeSeconds: 3,
  musicFadeInSeconds: 3,
  musicFadeOutSeconds: 3,
  voiceFadeSeconds: 0.08,
  duckGain: 0.35,
} as const;

type ActiveSegment = Segment & { audio_source_url: string };

function activeSegments(episode: LiveEpisode): ActiveSegment[] {
  const segments = episode.segments
    .filter((segment): segment is ActiveSegment => (
      ["AUDIO_READY", "COMMITTED", "PLAYED"].includes(segment.state) && Boolean(segment.audio_source_url)
    ))
    .sort((left, right) => left.order - right.order);
  if (!segments.length) throw new Error("cannot arrange an episode with no audio-ready segments");
  return segments;
}

function durationOf(segment: ActiveSegment): number {
  return Math.max(0, segment.duration_seconds ?? segment.actual_duration_seconds ?? segment.planned_duration_seconds);
}

function previousMusicIndex(segments: ActiveSegment[], index: number): number | undefined {
  for (let candidate = index - 1; candidate >= 0; candidate -= 1) {
    if (segments[candidate].kind === "MUSIC") return candidate;
  }
  return undefined;
}

function nextMusicIndex(segments: ActiveSegment[], index: number): number | undefined {
  for (let candidate = index + 1; candidate < segments.length; candidate += 1) {
    if (segments[candidate].kind === "MUSIC") return candidate;
  }
  return undefined;
}

function fadeFactor(offset: number, duration: number, fadeIn: number, fadeOut: number): number {
  if (fadeIn > 0 && offset < fadeIn) return Math.max(0, Math.min(1, offset / fadeIn));
  if (fadeOut > 0 && offset > duration - fadeOut) {
    return Math.max(0, Math.min(1, (duration - offset) / fadeOut));
  }
  return 1;
}

function uniquePoints(points: GainPoint[]): GainPoint[] {
  const byOffset = new Map<number, GainPoint>();
  for (const point of points) byOffset.set(Number(point.offsetSeconds.toFixed(6)), point);
  return [...byOffset.values()].sort((left, right) => left.offsetSeconds - right.offsetSeconds);
}

function musicAutomation(
  start: number,
  duration: number,
  fadeIn: number,
  fadeOut: number,
  narrationIntervals: Array<[number, number]>,
): GainPoint[] {
  const offsets = new Set<number>([0, duration]);
  if (fadeIn) offsets.add(Math.min(duration, fadeIn));
  if (fadeOut) offsets.add(Math.max(0, duration - fadeOut));
  for (const [narrationStart, narrationEnd] of narrationIntervals) {
    if (narrationEnd > start && narrationStart < start + duration) {
      offsets.add(Math.max(0, narrationStart - start));
      offsets.add(Math.min(duration, narrationEnd - start));
    }
  }

  return uniquePoints([...offsets].sort((left, right) => left - right).map((offset) => {
    const absolute = start + offset;
    const ducked = narrationIntervals.some(([begin, end]) => absolute >= begin && absolute < end);
    return {
      offsetSeconds: offset,
      gain: fadeFactor(offset, duration, fadeIn, fadeOut) * (ducked ? MIX_DEFAULTS.duckGain : 1),
    };
  }));
}

export function buildMixPlan(episode: LiveEpisode): MixPlan {
  const segments = activeSegments(episode);
  const starts: Record<string, number> = {};
  const startsByIndex = new Map<number, number>();
  let cursor = 0;

  segments.forEach((segment, index) => {
    const duration = durationOf(segment);
    let start = 0;
    if (index === 0) {
      start = 0;
    } else if (segment.kind === "MUSIC") {
      const priorMusic = previousMusicIndex(segments, index);
      if (priorMusic !== undefined) {
        const priorEnd = (startsByIndex.get(priorMusic) ?? 0) + durationOf(segments[priorMusic]);
        start = Math.max(0, priorEnd - MIX_DEFAULTS.crossfadeSeconds);
      } else {
        start = cursor;
      }
    } else if (segments[index - 1]?.kind === "MUSIC") {
      const previousEnd = (startsByIndex.get(index - 1) ?? 0) + durationOf(segments[index - 1]);
      start = Math.max(0, previousEnd - Math.min(MIX_DEFAULTS.outgoingVoiceOverlapSeconds, durationOf(segments[index - 1])));
    } else {
      start = cursor;
    }
    startsByIndex.set(index, start);
    starts[segment.id] = start;
    cursor = Math.max(cursor, start + duration);
  });

  const narrationIntervals: Array<[number, number]> = segments.flatMap((segment, index) => (
    segment.kind === "NARRATION"
      ? [[startsByIndex.get(index) ?? 0, (startsByIndex.get(index) ?? 0) + durationOf(segment)]] as Array<[number, number]>
      : []
  ));
  const clips: MixClip[] = segments.map((segment, index) => {
    const start = startsByIndex.get(index) ?? 0;
    const duration = durationOf(segment);
    if (segment.kind === "NARRATION") {
      return {
        id: `${segment.id}:voice`, segmentId: segment.id, sourceUrl: segment.audio_source_url,
        lane: "VOICE", timelineStartSeconds: start, sourceOffsetSeconds: 0,
        playableDurationSeconds: duration, gain: 1, fadeInSeconds: MIX_DEFAULTS.voiceFadeSeconds,
        fadeOutSeconds: MIX_DEFAULTS.voiceFadeSeconds,
        gainAutomation: [
          { offsetSeconds: 0, gain: 0 },
          { offsetSeconds: Math.min(MIX_DEFAULTS.voiceFadeSeconds, duration), gain: 1 },
          { offsetSeconds: Math.max(0, duration - MIX_DEFAULTS.voiceFadeSeconds), gain: 1 },
          { offsetSeconds: duration, gain: 0 },
        ],
      };
    }
    const fadeIn = previousMusicIndex(segments, index) !== undefined
      ? Math.min(MIX_DEFAULTS.musicFadeInSeconds, duration) : 0;
    const fadeOut = nextMusicIndex(segments, index) !== undefined
      ? Math.min(MIX_DEFAULTS.musicFadeOutSeconds, duration) : 0;
    return {
      id: `${segment.id}:music`, segmentId: segment.id, sourceUrl: segment.audio_source_url,
      lane: "MUSIC", timelineStartSeconds: start, sourceOffsetSeconds: 0,
      playableDurationSeconds: duration, gain: 1, fadeInSeconds: fadeIn, fadeOutSeconds: fadeOut,
      gainAutomation: musicAutomation(start, duration, fadeIn, fadeOut, narrationIntervals),
    };
  });

  return {
    episodeId: episode.id,
    durationSeconds: Math.max(...clips.map((clip) => clip.timelineStartSeconds + clip.playableDurationSeconds)),
    clips,
    segmentStarts: starts,
  };
}

export function activeMixClipsAt(plan: MixPlan, positionSeconds: number): MixClip[] {
  return plan.clips.filter((clip) => (
    positionSeconds >= clip.timelineStartSeconds
    && positionSeconds < clip.timelineStartSeconds + clip.playableDurationSeconds
  ));
}

export function evaluateGain(clip: MixClip, positionSeconds: number): number {
  const offset = positionSeconds - clip.timelineStartSeconds;
  if (offset < 0 || offset > clip.playableDurationSeconds) return 0;
  const points = clip.gainAutomation;
  if (!points.length) return clip.gain;
  if (offset <= points[0].offsetSeconds) return clip.gain * points[0].gain;
  for (let index = 1; index < points.length; index += 1) {
    const right = points[index];
    const left = points[index - 1];
    if (offset <= right.offsetSeconds) {
      const span = right.offsetSeconds - left.offsetSeconds;
      const ratio = span ? (offset - left.offsetSeconds) / span : 1;
      return clip.gain * (left.gain + (right.gain - left.gain) * ratio);
    }
  }
  return clip.gain * points[points.length - 1].gain;
}

export type ScheduledClip = { clip: MixClip; sourceTimeSeconds: number; gain: number };

export function scheduleAt(plan: MixPlan, positionSeconds: number): ScheduledClip[] {
  return activeMixClipsAt(plan, positionSeconds).map((clip) => ({
    clip,
    sourceTimeSeconds: clip.sourceOffsetSeconds + positionSeconds - clip.timelineStartSeconds,
    gain: evaluateGain(clip, positionSeconds),
  }));
}

export function clampMixPosition(plan: MixPlan, positionSeconds: number): number {
  return Math.max(0, Math.min(plan.durationSeconds, positionSeconds));
}

export function segmentIdAt(plan: MixPlan, positionSeconds: number): string | undefined {
  const active = activeMixClipsAt(plan, positionSeconds);
  return active.find((clip) => clip.lane === "VOICE")?.segmentId
    ?? active[active.length - 1]?.segmentId;
}
