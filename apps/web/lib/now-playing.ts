// Pure view-model helpers for the player, mini player and route sheet.
import { activeMixClipsAt, type MixPlan } from "./mix-timeline";
import { musicChaptersForEpisode } from "./playback";
import type { LiveEpisode, MusicSegment, ProgramRenderManifest, Segment } from "./types";

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

const TIER_SECONDS: Record<string, number> = { SHORT: 15 * 60, STANDARD: 30 * 60, DEEP: 60 * 60 };

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
  label: string;
  playing: boolean;
  ready: boolean;
  startSeconds: number | null;
};

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
  return musicChaptersForEpisode(episode).map((chapter, index) => {
    const startOf = (segment: Segment) => plan?.segmentStarts[segment.id] ?? null;
    const starts = chapter.segments.map(startOf).filter((value): value is number => value !== null);
    const tracks = chapter.segments
      .filter((segment): segment is MusicSegment => segment.kind === "MUSIC")
      .map((segment) => {
        const start = startOf(segment);
        const ready = READY_STATES.has(segment.state)
          && Boolean(segment.audio_source_url)
          && start !== null
          && start < frontier;
        return {
          id: segment.id,
          label: trackLabel(segment),
          playing: segment.id === currentMusicId,
          ready,
          startSeconds: start,
        };
      });
    const playing = tracks.some((track) => track.playing);
    const ready = tracks.length > 0 && tracks.every((track) => track.ready);
    return {
      id: chapter.id,
      index,
      title: `第 ${index + 1} 段`,
      startSeconds: starts.length ? Math.min(...starts) : null,
      status: playing ? "playing" : ready ? "ready" : "preparing",
      tracks: tracks.length ? tracks : [{ id: chapter.id + ":tbd", label: "曲目待定", playing: false, ready: false, startSeconds: null }],
    };
  });
}
