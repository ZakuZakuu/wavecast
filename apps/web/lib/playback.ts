import type { LiveEpisode, Segment } from "./types";
import type { MixPlan } from "./mix-timeline";

export type MusicChapter = { id: string; segments: Segment[] };

export function musicChaptersForEpisode(episode: LiveEpisode): MusicChapter[] {
  const active = [...episode.segments]
    .filter((segment) => segment.state !== "SKIPPED")
    .sort((left, right) => left.order - right.order);
  const chapters: MusicChapter[] = [];
  for (const music of active.filter((segment) => segment.kind === "MUSIC")) {
    if (!chapters.some((chapter) => chapter.id === music.chapter_id)) {
      chapters.push({ id: music.chapter_id, segments: [] });
    }
  }
  for (const segment of active) {
    // A standalone host bridge belongs with its incoming music in the UI;
    // an outro belongs with the final music. Neither increments song numbering.
    const chapter = chapters.find((item) => item.id === segment.chapter_id)
      ?? chapters.find((item) => active.some((music) => (
        music.kind === "MUSIC"
        && music.chapter_id === item.id
        && music.order > segment.order
      )))
      ?? chapters.at(-1);
    chapter?.segments.push(segment);
  }
  return chapters;
}

export function nextProgramMusicStart(plan: MixPlan, positionSeconds: number): number | undefined {
  return plan.clips
    .filter((clip) => clip.lane === "MUSIC" && clip.timelineStartSeconds > positionSeconds + 0.05)
    .map((clip) => clip.timelineStartSeconds)
    .sort((left, right) => left - right)[0];
}


const PLAYBACK_READY_STATES = new Set(["AUDIO_READY", "COMMITTED", "PLAYED"]);

export function isPlaybackReadySegment(segment: Segment | undefined): boolean {
  return Boolean(
    segment
    && segment.audio_source_url
    && PLAYBACK_READY_STATES.has(segment.state),
  );
}

export function shouldArmHandoff(options: {
  current: Segment | undefined;
  upcoming: Segment | undefined;
  serverCurrentId: string | null;
  transportSegmentId: string | null;
  remainingSeconds: number;
  armThresholdSeconds: number;
}): boolean {
  const {
    current,
    upcoming,
    serverCurrentId,
    transportSegmentId,
    remainingSeconds,
    armThresholdSeconds,
  } = options;
  return Boolean(
    current
    && upcoming
    && current.id !== upcoming.id
    && transportSegmentId === null
    && serverCurrentId === current.id
    && remainingSeconds <= armThresholdSeconds
    && isPlaybackReadySegment(upcoming),
  );
}

export function canUseArmedHandoff(options: {
  current: Segment | undefined;
  armedSegment: Segment | undefined;
  serverCurrentId: string | null;
  armedFromSegmentId: string | null;
}): boolean {
  const {
    current,
    armedSegment,
    serverCurrentId,
    armedFromSegmentId,
  } = options;
  return Boolean(
    current
    && armedSegment
    && current.id !== armedSegment.id
    && serverCurrentId === current.id
    && armedFromSegmentId === current.id
    && isPlaybackReadySegment(armedSegment),
  );
}

export function shouldSuppressSeekConflict(options: {
  status: number;
  withinCurrent: boolean;
}): boolean {
  return options.status === 409 && options.withinCurrent;
}

export type PlaybackAnchor = Pick<LiveEpisode, "current_segment_id" | "playback_position_seconds">;

export function playbackAnchor(episode: LiveEpisode | null): PlaybackAnchor | null {
  if (!episode) return null;
  return {
    current_segment_id: episode.current_segment_id,
    playback_position_seconds: episode.playback_position_seconds,
  };
}

export function reconcileBrowserPosition(
  browserPosition: number,
  previousAnchor: PlaybackAnchor | null,
  nextEpisode: LiveEpisode | null,
  explicitTransportPosition: number | null = null,
): number {
  const nextAnchor = playbackAnchor(nextEpisode);
  if (!nextAnchor) return 0;
  if (explicitTransportPosition !== null) return Math.max(0, explicitTransportPosition);
  if (!previousAnchor || previousAnchor.current_segment_id !== nextAnchor.current_segment_id) {
    return nextAnchor.playback_position_seconds;
  }
  return browserPosition;
}

export function segmentStart(episode: LiveEpisode, segmentId: string): number {
  let total = 0;
  for (const segment of [...episode.segments].sort((a, b) => a.order - b.order)) {
    if (segment.state === "SKIPPED") continue;
    if (segment.id === segmentId) return total;
    total += segment.duration_seconds ?? segment.actual_duration_seconds ?? segment.planned_duration_seconds;
  }
  return total;
}

export function segmentAtPosition(
  episode: LiveEpisode,
  positionSeconds: number,
): Segment | undefined {
  let start = 0;
  for (const segment of [...episode.segments].sort((a, b) => a.order - b.order)) {
    if (segment.state === "SKIPPED") continue;
    const duration = segment.duration_seconds
      ?? segment.actual_duration_seconds
      ?? segment.planned_duration_seconds;
    const end = start + duration;
    if (start <= positionSeconds && positionSeconds < end) {
      return segment;
    }
    start = end;
  }
  return undefined;
}

export function segmentOffset(episode: LiveEpisode, segmentId: string, timelinePosition: number): number {
  return Math.max(0, timelinePosition - segmentStart(episode, segmentId));
}

export function remainingSegmentSeconds(episode: LiveEpisode, segment: Segment): number {
  const duration = segment.duration_seconds ?? segment.actual_duration_seconds ?? segment.planned_duration_seconds;
  return Math.max(0, duration - Math.max(0, episode.playback_position_seconds - segmentStart(episode, segment.id)));
}

export function isSeekAllowed(episode: LiveEpisode, targetSeconds: number): boolean {
  return targetSeconds >= 0 && targetSeconds <= episode.generated_frontier_seconds;
}

export function isProgramPlaybackComplete(episode: LiveEpisode): boolean {
  const activeSegments = episode.segments.filter((segment) => segment.state !== "SKIPPED");
  const reachedPlannedFrontier =
    episode.state === "MATERIALIZED"
    || episode.state === "PUBLISHED"
    || episode.generated_frontier_seconds >= episode.program_estimated_duration_seconds;
  return activeSegments.length > 0
    && !episode.is_playing
    && reachedPlannedFrontier
    && activeSegments.every((segment) => segment.state === "PLAYED");
}

export function nextVisibleSegment(
  episode: LiveEpisode,
  afterSegmentId: string | null = episode.current_segment_id,
): Segment | undefined {
  const current = episode.segments.find((segment) => segment.id === afterSegmentId);
  return episode.segments
    .filter((segment) => segment.order > (current?.order ?? -1))
    .find((segment) => ["AUDIO_READY", "COMMITTED", "PLAYED"].includes(segment.state))
    ?? episode.segments
      .filter((segment) => segment.order > (current?.order ?? -1))
      .find((segment) => segment.kind === "MUSIC");
}

export function formatSeconds(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${Math.floor(seconds % 60).toString().padStart(2, "0")}`;
}
