import type { LiveEpisode, Segment } from "./types";

export function isSeekAllowed(episode: LiveEpisode, targetSeconds: number): boolean {
  return targetSeconds >= 0 && targetSeconds <= episode.generated_frontier_seconds;
}

export function nextVisibleSegment(episode: LiveEpisode): Segment | undefined {
  const current = episode.segments.find((segment) => segment.id === episode.current_segment_id);
  return episode.segments
    .filter((segment) => segment.order > (current?.order ?? -1))
    .find((segment) => ["AUDIO_READY", "COMMITTED", "PLAYED"].includes(segment.state))
    ?? episode.segments.filter((segment) => segment.order > (current?.order ?? -1)).find((segment) => segment.kind === "MUSIC");
}

export function formatSeconds(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${Math.floor(seconds % 60).toString().padStart(2, "0")}`;
}
