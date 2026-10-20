import type { LiveEpisode } from "./types";

export function durationNoticeText(notice: LiveEpisode["duration_notice"]): string | null {
  if (!notice) return null;
  const actual = Math.max(1, Math.round(notice.actual_seconds / 60));
  const target = Math.max(1, Math.round(notice.target_seconds / 60));
  return `实际约 ${actual} 分钟，未达到目标约 ${target} 分钟。`;
}
