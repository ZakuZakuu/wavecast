// Home "猜你想听" / "先听这几档" card helpers.
import { DURATIONS, STATIONS, type StationId } from "./stations";

/** Recommendations become short-tier programmes (backend default). */
export const RECOMMENDATION_MINUTES = DURATIONS.find((option) => option.value === "SHORT")?.minutes ?? 35;

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

/**
 * The station the backend chose for a recommended idea, when it is one we know; otherwise undefined
 * so the caller falls back to guessing from the copy (ideas made before stations were chosen).
 */
export function ideaStation(idea: { station?: string | null }): StationId | undefined {
  return STATIONS.find((station) => station.id === idea.station)?.id;
}
