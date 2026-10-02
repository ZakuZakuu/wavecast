// Pure view helpers for the library list.
import { formatClock } from "./now-playing";
import type { RecentProgramRecord, SavedEpisodeRecord } from "./user-library";

const DAY_MS = 24 * 60 * 60 * 1000;
const WEEKDAYS = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];

/**
 * One row per programme: several episodes of the same programme (seed) collapse
 * to the most recently updated one. Sorted newest first.
 */
export function dedupeByProgramme<T extends Pick<RecentProgramRecord, "seedId" | "updatedAt">>(records: T[]): T[] {
  const latest = new Map<string, T>();
  for (const record of records) {
    const existing = latest.get(record.seedId);
    if (!existing || record.updatedAt > existing.updatedAt) latest.set(record.seedId, record);
  }
  return [...latest.values()].sort((left, right) => right.updatedAt - left.updatedAt);
}

function startOfDay(timestamp: number): number {
  const date = new Date(timestamp);
  date.setHours(0, 0, 0, 0);
  return date.getTime();
}

/** 刚刚 / N 分钟前 / 今天 / 昨天 / 周二 / 9月12日 */
export function relativeWhen(timestamp: number, now = Date.now()): string {
  const diff = now - timestamp;
  if (diff < 5 * 60 * 1000) return "刚刚";
  if (diff < 60 * 60 * 1000) return `${Math.floor(diff / 60000)} 分钟前`;
  const days = Math.round((startOfDay(now) - startOfDay(timestamp)) / DAY_MS);
  if (days <= 0) return "今天";
  if (days === 1) return "昨天";
  if (days < 7) return WEEKDAYS[new Date(timestamp).getDay()];
  const date = new Date(timestamp);
  return `${date.getMonth() + 1}月${date.getDate()}日`;
}

export function isFinished(progressSeconds: number, durationSeconds: number): boolean {
  return durationSeconds > 0 && progressSeconds >= durationSeconds - 5;
}

export function progressRatio(progressSeconds: number, durationSeconds: number): number {
  if (durationSeconds <= 0) return 0;
  return Math.min(1, Math.max(0, progressSeconds / durationSeconds));
}

/** "听到 12:40，刚刚" or "听完了，昨天". Never internal segment names. */
export function listeningStatus(
  record: Pick<RecentProgramRecord, "progressSeconds" | "durationSeconds" | "updatedAt">,
  now = Date.now(),
): string {
  const when = relativeWhen(record.updatedAt, now);
  if (isFinished(record.progressSeconds, record.durationSeconds)) return `听完了，${when}`;
  if (record.progressSeconds < 1) return `还没开始听，${when}`;
  return `听到 ${formatClock(record.progressSeconds)}，${when}`;
}

export type LibraryRow = (RecentProgramRecord | SavedEpisodeRecord) & { kind: "episode" };
