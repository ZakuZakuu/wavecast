import type { LiveEpisode, Segment } from "./types";

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
