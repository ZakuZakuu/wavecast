// Home "猜你想听" / "先听这几档" card helpers.
import { DURATIONS } from "./stations";

/** Recommendations become STANDARD-length programmes (backend default). */
export const RECOMMENDATION_MINUTES = DURATIONS.find((option) => option.value === "STANDARD")?.minutes ?? 30;

function titleKey(title: string): string {
  return title.normalize("NFKC").replace(/\s+/g, " ").trim().toLowerCase();
}

/** Same-titled programmes collapse to the first one, order kept. */
export function dedupeByTitle<T extends { title: string }>(items: readonly T[]): T[] {
  const seen = new Set<string>();
  const out: T[] = [];
  for (const item of items) {
    const key = titleKey(item.title);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(item);
  }
  return out;
}

/** Second line under a card: "夜里，约 30 分钟" (station only when unknown). */
export function pickMeta(stationName: string, minutes: number | null): string {
  return minutes ? `${stationName}，约 ${minutes} 分钟` : stationName;
}
