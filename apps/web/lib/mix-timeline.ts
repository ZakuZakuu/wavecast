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
  schemaVersion: 1;
  episodeId: string;
  durationSeconds: number;
  clips: MixClip[];
  segmentStarts: Record<string, number>;
};

export function mixPlanSignature(episode: Pick<LiveEpisode, "segments">): string {
  return episode.segments.map((item) => {
    const arrangementState = item.state === "SKIPPED"
      ? "skipped"
      : ["AUDIO_READY", "COMMITTED", "PLAYED"].includes(item.state)
        ? "ready"
        : "pending";
    return [
      item.id,
      item.order,
      item.kind,
      arrangementState,
      item.audio_source_url,
      item.duration_seconds,
    ].join(":");
  }).join("|");
}

export function parseMixPlan(value: unknown): MixPlan {
  if (!value || typeof value !== "object") throw new Error("Invalid MixPlan");
  const candidate = value as Partial<MixPlan>;
  if (candidate.schemaVersion !== 1 || typeof candidate.episodeId !== "string"
      || typeof candidate.durationSeconds !== "number"
      || !Array.isArray(candidate.clips) || typeof candidate.segmentStarts !== "object") {
    throw new Error("Invalid MixPlan contract");
  }
  return value as MixPlan;
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

export function overlapLeadSeconds(
  current: MixClip | null | undefined,
  next: MixClip | null | undefined,
): number {
  if (!current || !next) return 0;
  const currentEnd = current.timelineStartSeconds + current.playableDurationSeconds;
  return Math.max(
    0,
    Math.min(current.playableDurationSeconds, currentEnd - next.timelineStartSeconds),
  );
}

export function segmentIdAt(plan: MixPlan, positionSeconds: number): string | undefined {
  const active = activeMixClipsAt(plan, positionSeconds);
  return active.find((clip) => clip.lane === "VOICE")?.segmentId
    ?? active[active.length - 1]?.segmentId;
}


export type MixTransport = {
  mixPositionSeconds: number;
  linearPositionSeconds: number;
  segmentId?: string;
};

function linearSegmentStart(episode: LiveEpisode, segmentId: string): number {
  let total = 0;
  for (const segment of [...episode.segments].sort((left, right) => left.order - right.order)) {
    if (segment.state !== "SKIPPED") {
      if (segment.id === segmentId) return total;
      total += segment.duration_seconds ?? segment.actual_duration_seconds ?? segment.planned_duration_seconds;
    }
  }
  return total;
}

function linearSegmentAt(episode: LiveEpisode, positionSeconds: number): Segment | undefined {
  let total = 0;
  for (const segment of [...episode.segments].sort((left, right) => left.order - right.order)) {
    if (segment.state === "SKIPPED") continue;
    const duration = segment.duration_seconds ?? segment.actual_duration_seconds ?? segment.planned_duration_seconds;
    if (positionSeconds >= total && positionSeconds < total + duration) return segment;
    total += duration;
  }
  return undefined;
}

export function mixPositionToLinearPosition(
  episode: LiveEpisode,
  plan: MixPlan,
  positionSeconds: number,
): MixTransport {
  const mixPosition = clampMixPosition(plan, positionSeconds);
  const active = activeMixClipsAt(plan, mixPosition);
  const clip = active.find((candidate) => candidate.lane === "VOICE") ?? active[active.length - 1];
  if (!clip) return { mixPositionSeconds: mixPosition, linearPositionSeconds: mixPosition };

  const offset = Math.max(
    0,
    Math.min(clip.playableDurationSeconds, mixPosition - clip.timelineStartSeconds),
  );
  return {
    mixPositionSeconds: mixPosition,
    linearPositionSeconds: linearSegmentStart(episode, clip.segmentId) + offset,
    segmentId: clip.segmentId,
  };
}

export function linearPositionToMixPosition(
  episode: LiveEpisode,
  plan: MixPlan,
  positionSeconds: number,
): MixTransport {
  const linearPosition = Math.max(0, positionSeconds);
  const segment = linearSegmentAt(episode, linearPosition);
  if (!segment) return { mixPositionSeconds: clampMixPosition(plan, linearPosition), linearPositionSeconds: linearPosition };
  const clip = plan.clips.find((candidate) => candidate.segmentId === segment.id);
  if (!clip) return { mixPositionSeconds: clampMixPosition(plan, linearPosition), linearPositionSeconds: linearPosition };
  const offset = Math.max(0, Math.min(clip.playableDurationSeconds, linearPosition - linearSegmentStart(episode, segment.id)));
  return {
    mixPositionSeconds: clampMixPosition(plan, clip.timelineStartSeconds + offset),
    linearPositionSeconds: linearPosition,
    segmentId: segment.id,
  };
}
