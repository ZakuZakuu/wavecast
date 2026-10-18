// Pure view-model helpers for the player, mini player and route sheet.
import { activeMixClipsAt, type MixPlan } from "./mix-timeline";
import { musicChaptersForEpisode, programmeJumpPoints } from "./playback";
import type { LiveEpisode, MusicSegment, NarrationSegment, ProgramRenderManifest, Segment } from "./types";

const READY_STATES = new Set(["AUDIO_READY", "COMMITTED", "PLAYED"]);

/** "12:40", or "1:02:05" past an hour. */
export function formatClock(totalSeconds: number): string {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = String(seconds % 60).padStart(2, "0");
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, "0")}:${rest}`
    : `${String(minutes).padStart(2, "0")}:${rest}`;
}

const TIER_SECONDS: Record<string, number> = { SHORT: 35 * 60, STANDARD: 35 * 60, DEEP: 60 * 60 };

/**
 * Estimated programme length for the right-hand progress label. A complete
 * stream is exact; otherwise use the backend estimate, never shorter than
 * what is already prepared; fall back to the duration tier.
 */
export function estimatedTotalSeconds(
  episode: Pick<LiveEpisode, "program_estimated_duration_seconds">,
  manifest: Pick<ProgramRenderManifest, "renderedFrontierSeconds" | "complete"> | null,
  durationTier?: string | null,
): number {
  const frontier = manifest?.renderedFrontierSeconds ?? 0;
  if (manifest?.complete && frontier > 0) return frontier;
  const estimate = episode.program_estimated_duration_seconds > 0
    ? episode.program_estimated_duration_seconds
    : TIER_SECONDS[durationTier ?? ""] ?? TIER_SECONDS.STANDARD;
  return Math.max(estimate, frontier);
}

export type ProgressLayers = { playedPct: number; preparedPct: number };

export function progressLayers(position: number, frontier: number, total: number): ProgressLayers {
  const span = Math.max(1, total);
  const clamp = (value: number) => Math.min(100, Math.max(0, (value / span) * 100));
  const prepared = clamp(frontier);
  return { playedPct: Math.min(prepared, clamp(position)), preparedPct: prepared };
}

/** Clamp a requested seek to the prepared frontier; report whether it overshot. */
export function clampSeek(target: number, frontier: number): { position: number; overshoot: boolean } {
  const max = Math.max(0, frontier);
  return { position: Math.max(0, Math.min(target, max)), overshoot: target > max + 0.5 };
}

/** The music under the playhead (narration may sit over music). */
export function currentMusicSegment(
  episode: LiveEpisode,
  plan: MixPlan | null,
  position: number,
  fallback?: Segment,
): MusicSegment | undefined {
  const byId = (id: string) => episode.segments.find((segment) => segment.id === id);
  if (plan) {
    const active = activeMixClipsAt(plan, position).filter((clip) => clip.lane === "MUSIC");
    const clip = active.at(-1)
      ?? [...plan.clips]
        .filter((candidate) => candidate.lane === "MUSIC" && candidate.timelineStartSeconds <= position)
        .sort((left, right) => right.timelineStartSeconds - left.timelineStartSeconds)[0];
    const segment = clip ? byId(clip.segmentId) : undefined;
    if (segment?.kind === "MUSIC") return segment;
  }
  if (fallback?.kind === "MUSIC") return fallback;
  const ordered = [...episode.segments].sort((left, right) => left.order - right.order);
  const index = fallback ? ordered.findIndex((segment) => segment.id === fallback.id) : -1;
  const before = ordered.slice(0, index >= 0 ? index : ordered.length).reverse()
    .find((segment): segment is MusicSegment => segment.kind === "MUSIC");
  return before ?? ordered.find((segment): segment is MusicSegment => segment.kind === "MUSIC");
}

export function trackLabel(segment: Pick<MusicSegment, "title" | "artist">): string {
  const title = segment.title?.trim();
  if (!title) return "曲目待定";
  return segment.artist ? `${segment.artist}《${title}》` : `《${title}》`;
}

export type RouteTrack = {
  id: string;
  /** A song, or a piece of host speech listed beside the songs. */
  kind: "MUSIC" | "VOICE";
  label: string;
  playing: boolean;
  ready: boolean;
  startSeconds: number | null;
};

const NARRATION_ROLE_LABEL = {
  INTRO: "开场",
  TRACK_INTRO: "歌曲介绍",
  TRANSITION: "串场",
  OUTRO: "收尾",
  GENERAL: "主持",
} as const;

/**
 * Route label of a piece of host speech: the writer's heading when there is one, otherwise its
 * role (and the song it leads into). The segment's own `title` is an internal placeholder and is
 * never shown. Programmes without a stored role are told apart by where the speech sits.
 */
export function narrationLabel(segment: NarrationSegment, episode: Pick<LiveEpisode, "segments">): string {
  const heading = segment.display_title?.trim();
  if (heading) return heading;
  const music = episode.segments
    .filter((candidate): candidate is MusicSegment => candidate.kind === "MUSIC" && candidate.state !== "SKIPPED")
    .sort((left, right) => left.order - right.order);
  const next = music.find((candidate) => candidate.order > segment.order);
  const role = segment.hosting_role === "opening" ? "开场"
    : segment.hosting_role === "closing" ? "收尾"
      : segment.narration_role && segment.narration_role !== "GENERAL" ? NARRATION_ROLE_LABEL[segment.narration_role]
        : !music.some((candidate) => candidate.order < segment.order) ? "开场"
          : !next ? "收尾"
            : "串场";
  return next && role !== "收尾" && next.title?.trim() ? `${role} · 引出${trackLabel(next)}` : role;
}

export type RouteChapter = {
  id: string;
  index: number;
  title: string;
  startSeconds: number | null;
  status: "playing" | "ready" | "preparing";
  tracks: RouteTrack[];
};

/**
 * Programme route. Chapter names are not in the API yet, so chapters are
 * "第 N 段" (no hard-coded editorial titles). A track is jumpable only when its
 * audio is ready and its start lies inside the prepared frontier.
 */
export function routeChapters(
  episode: LiveEpisode,
  plan: MixPlan | null,
  currentMusicId: string | null,
  frontier: number,
): RouteChapter[] {
  // Speech is listed only where next/previous can land on it: published, playable, once per run.
  const voiceStarts = new Map(
    (plan ? programmeJumpPoints(plan, episode) : [])
      .filter((point) => point.lane === "VOICE" && point.startSeconds < frontier)
      .map((point) => [point.segmentId, point.startSeconds]),
  );
  return musicChaptersForEpisode(episode).map((chapter, index) => {
    const startOf = (segment: Segment) => plan?.segmentStarts[segment.id] ?? null;
    const starts = chapter.segments.map(startOf).filter((value): value is number => value !== null);
    const rows = chapter.segments.flatMap((segment): RouteTrack[] => {
      if (segment.kind === "NARRATION") {
        const start = voiceStarts.get(segment.id);
        return start === undefined ? [] : [{
          id: segment.id,
          kind: "VOICE",
          label: narrationLabel(segment, episode),
          playing: false,
          ready: true,
          startSeconds: start,
        }];
      }
      const start = startOf(segment);
      const ready = READY_STATES.has(segment.state)
        && Boolean(segment.audio_source_url)
        && start !== null
        && start < frontier;
      return [{
        id: segment.id,
        kind: "MUSIC",
        label: trackLabel(segment),
        playing: segment.id === currentMusicId,
        ready,
        startSeconds: start,
      }];
    });
    const songs = rows.filter((row) => row.kind === "MUSIC");
    const playing = songs.some((track) => track.playing);
    const ready = songs.length > 0 && songs.every((track) => track.ready);
    return {
      id: chapter.id,
      index,
      title: `第 ${index + 1} 段`,
      startSeconds: starts.length ? Math.min(...starts) : null,
      status: playing ? "playing" : ready ? "ready" : "preparing",
      tracks: songs.length ? rows : [{ id: chapter.id + ":tbd", kind: "MUSIC", label: "曲目待定", playing: false, ready: false, startSeconds: null }],
    };
  });
}

/** The next music after the playhead (MixPlan order, falling back to segment order). */
export function nextMusicSegment(
  episode: LiveEpisode,
  plan: MixPlan | null,
  position: number,
  currentMusicId: string | null,
): MusicSegment | undefined {
  const byId = (id: string) => episode.segments.find((segment) => segment.id === id);
  if (plan) {
    const next = plan.clips
      .filter((clip) => clip.lane === "MUSIC" && clip.timelineStartSeconds > position + 0.05 && clip.segmentId !== currentMusicId)
      .sort((left, right) => left.timelineStartSeconds - right.timelineStartSeconds)[0];
    const segment = next ? byId(next.segmentId) : undefined;
    if (segment?.kind === "MUSIC") return segment;
  }
  const ordered = [...episode.segments]
    .filter((segment) => segment.state !== "SKIPPED")
    .sort((left, right) => left.order - right.order);
  const index = currentMusicId ? ordered.findIndex((segment) => segment.id === currentMusicId) : -1;
  return ordered.slice(index + 1).find((segment): segment is MusicSegment => segment.kind === "MUSIC");
}

/** 1-based chapter ("第 N 段") that contains a segment, or null. */
export function chapterNumberOf(episode: LiveEpisode, segmentId: string | null | undefined): number | null {
  if (!segmentId) return null;
  const index = musicChaptersForEpisode(episode)
    .findIndex((chapter) => chapter.segments.some((segment) => segment.id === segmentId));
  return index >= 0 ? index + 1 : null;
}

/** Timeline start and duration of a narration (VOICE) clip, when the MixPlan has it. */
export function voiceClipTiming(
  plan: MixPlan | null,
  segmentId: string,
): { startSeconds: number; durationSeconds: number } | null {
  const clip = plan?.clips.find((candidate) => candidate.lane === "VOICE" && candidate.segmentId === segmentId);
  return clip ? { startSeconds: clip.timelineStartSeconds, durationSeconds: clip.playableDurationSeconds } : null;
}


/**
 * Everything the host has said that is already published, in programme order: narration segments
 * that are ready (not skipped, not a draft) and whose voice clip starts inside the published audio.
 * It comes from the programme itself, so it is the same after a resume or a remount, and it does not
 * depend on the listener having been there while it was spoken.
 */
export function publishedNarration(
  episode: Pick<LiveEpisode, "segments">,
  plan: MixPlan | null,
  frontierSeconds: number,
): Array<{ id: string; text: string }> {
  if (!plan) return [];
  const ready = new Set(["AUDIO_READY", "COMMITTED", "PLAYED"]);
  const byId = new Map(episode.segments.map((segment) => [segment.id, segment]));
  return plan.clips
    .filter((clip) => clip.lane === "VOICE" && clip.timelineStartSeconds < frontierSeconds)
    .sort((left, right) => left.timelineStartSeconds - right.timelineStartSeconds)
    .flatMap((clip) => {
      const segment = byId.get(clip.segmentId);
      const text = segment?.kind === "NARRATION" ? segment.narration_text?.trim() : "";
      return segment && text && ready.has(segment.state) ? [{ id: segment.id, text }] : [];
    });
}
