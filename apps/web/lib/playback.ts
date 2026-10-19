import type { LiveEpisode, ProgramRenderManifest, Segment } from "./types";
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

/** Host speech that starts this soon after the previous clip ended is the same piece of speech. */
const VOICE_JOIN_SECONDS = 1.5;
/** Starts closer than this are one place on the timeline. */
const SAME_START_SECONDS = 0.05;

/** `endSeconds` is the end of the clip, or of the last clip of a run of consecutive host speech. */
export type JumpPoint = { segmentId: string; lane: "MUSIC" | "VOICE"; startSeconds: number; endSeconds: number };

/**
 * Every place next/previous/the route can land: the start of each song and the start of each
 * piece of host speech, side by side. Speech counts only when it is published and playable (not
 * skipped, not a draft) and consecutive clips count once, at the first. Pass the episode to
 * apply that filter; without it every voice clip in the plan counts.
 */
export function programmeJumpPoints(plan: MixPlan, episode?: Pick<LiveEpisode, "segments">): JumpPoint[] {
  const segments = episode ? new Map(episode.segments.map((segment) => [segment.id, segment])) : null;
  const music: JumpPoint[] = plan.clips
    .filter((clip) => clip.lane === "MUSIC")
    .map((clip) => ({
      segmentId: clip.segmentId,
      lane: "MUSIC",
      startSeconds: clip.timelineStartSeconds,
      endSeconds: clip.timelineStartSeconds + clip.playableDurationSeconds,
    }));
  const voice: JumpPoint[] = [];
  let run: JumpPoint | null = null;
  const speech = plan.clips
    .filter((clip) => clip.lane === "VOICE")
    .filter((clip) => {
      if (!segments) return true;
      const segment = segments.get(clip.segmentId);
      return segment?.kind === "NARRATION" && isPlaybackReadySegment(segment);
    })
    .sort((left, right) => left.timelineStartSeconds - right.timelineStartSeconds);
  for (const clip of speech) {
    const end = clip.timelineStartSeconds + clip.playableDurationSeconds;
    if (!run || clip.timelineStartSeconds > run.endSeconds + VOICE_JOIN_SECONDS) {
      run = { segmentId: clip.segmentId, lane: "VOICE", startSeconds: clip.timelineStartSeconds, endSeconds: end };
      voice.push(run);
    } else {
      run.endSeconds = Math.max(run.endSeconds, end);
    }
  }
  const points: JumpPoint[] = [];
  for (const point of [...music, ...voice].sort((left, right) => left.startSeconds - right.startSeconds)) {
    const last = points.at(-1);
    if (!last || point.startSeconds - last.startSeconds >= SAME_START_SECONDS) points.push(point);
  }
  return points;
}

export function nextJumpStart(
  plan: MixPlan,
  positionSeconds: number,
  episode?: Pick<LiveEpisode, "segments">,
): number | undefined {
  return programmeJumpPoints(plan, episode)
    .find((point) => point.startSeconds > positionSeconds + SAME_START_SECONDS)?.startSeconds;
}

/**
 * Where "previous" goes, as in any music player: back to the start of what is playing if it has
 * played for a few seconds, otherwise to the start of the one before it (the first simply
 * restarts). Songs and host speech are the same kind of place here.
 */
export function previousJumpStart(
  plan: MixPlan,
  positionSeconds: number,
  episode?: Pick<LiveEpisode, "segments">,
  restartAfterSeconds = 3,
): number {
  const starts = programmeJumpPoints(plan, episode).map((point) => point.startSeconds);
  const playing = starts.filter((start) => start <= positionSeconds + SAME_START_SECONDS);
  if (!playing.length) return 0;
  const current = playing[playing.length - 1];
  if (positionSeconds - current > restartAfterSeconds) return current;
  return playing.length > 1 ? playing[playing.length - 2] : current;
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

/** How far ahead of the listener a finished programme's rendered audio should reach. */
export const RENDER_LEAD_SECONDS = 240;

/**
 * A finished programme is rendered a few minutes at a time: while the audio rendered so far is not
 * the whole programme, more is asked for before the listener gets to the end of it.
 */
export function shouldExtendRender(options: {
  episodeState: LiveEpisode["state"] | null;
  manifest: Pick<ProgramRenderManifest, "complete" | "renderedFrontierSeconds" | "chunks"> | null;
  positionSeconds: number;
}): boolean {
  const { episodeState, manifest, positionSeconds } = options;
  if (episodeState !== "MATERIALIZED" && episodeState !== "PUBLISHED") return false;
  if (!manifest || manifest.complete || manifest.chunks.length === 0) return false;
  return manifest.renderedFrontierSeconds - positionSeconds < RENDER_LEAD_SECONDS;
}
