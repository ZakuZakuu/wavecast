import type { LiveEpisode, Segment } from "./types";

export function segmentStart(episode: LiveEpisode, segmentId: string): number {
  let total = 0;
  for (const segment of [...episode.segments].sort((a, b) => a.order - b.order)) {
    if (segment.state === "SKIPPED") continue;
    if (segment.id === segmentId) return total;
    total += segment.actual_duration_seconds ?? segment.planned_duration_seconds;
  }
  return total;
}

export function remainingSegmentSeconds(episode: LiveEpisode, segment: Segment): number {
  const duration = segment.actual_duration_seconds ?? segment.planned_duration_seconds;
  return Math.max(0, duration - Math.max(0, episode.playback_position_seconds - segmentStart(episode, segment.id)));
}

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
