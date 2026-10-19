import { api } from "./api";
import type { FullVersionItem, FullVersionState, LiveEpisode } from "./types";

// A 完整版 is prepared on the server while the listener is elsewhere. This device keeps a short list
// of the ones it asked for and has not yet seen finish, polls only while that list is not empty, and
// remembers which finished ones the listener has not been told about (the dot on 节目库).
const WATCH_KEY = "wavecast-full-watch-v1";
const UNSEEN_KEY = "wavecast-full-unseen-v1";
const CHANGE_EVENT = "wavecast-full-versions-change";
/** How often the pending ones are asked about. */
export const FULL_VERSION_POLL_MS = 8000;
/** A pending one older than this has surely failed or finished unseen (the server gives up after 20 minutes). */
const WATCH_TTL_MS = 60 * 60 * 1000;

export type WatchedFullVersion = {
  episodeId: string;
  programmeId: string;
  title: string;
  since: number;
};

function read(key: string): WatchedFullVersion[] {
  try {
    const parsed: unknown = JSON.parse(window.localStorage.getItem(key) ?? "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((item): item is WatchedFullVersion => (
      typeof item?.episodeId === "string" && typeof item?.programmeId === "string"
      && typeof item?.title === "string" && typeof item?.since === "number"
    ));
  } catch {
    return [];
  }
}

function write(key: string, items: WatchedFullVersion[]): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(items));
  } catch {
    // Without storage the reminder is simply lost; the library still shows the state.
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

export function readWatchedFullVersions(now = Date.now()): WatchedFullVersion[] {
  return read(WATCH_KEY).filter((item) => now - item.since < WATCH_TTL_MS);
}

export function watchFullVersion(item: Omit<WatchedFullVersion, "since">): void {
  const others = read(WATCH_KEY).filter((existing) => existing.episodeId !== item.episodeId);
  write(WATCH_KEY, [...others, { ...item, since: Date.now() }]);
}

export function unwatchFullVersion(episodeId: string): void {
  const kept = read(WATCH_KEY).filter((item) => item.episodeId !== episodeId);
  if (kept.length !== read(WATCH_KEY).length) write(WATCH_KEY, kept);
}

export function readUnseenFullVersions(): WatchedFullVersion[] {
  return read(UNSEEN_KEY);
}

/** The listener has opened 节目库: nothing is waiting to be noticed any more. */
export function clearUnseenFullVersions(): void {
  if (read(UNSEEN_KEY).length) write(UNSEEN_KEY, []);
}

export function subscribeFullVersions(listener: () => void): () => void {
  window.addEventListener(CHANGE_EVENT, listener);
  window.addEventListener("storage", listener);
  return () => {
    window.removeEventListener(CHANGE_EVENT, listener);
    window.removeEventListener("storage", listener);
  };
}

/**
 * Asks about everything on the watch list. Finished ones leave the list and go to the unseen list
 * (and are returned, for a banner); failed ones just leave it, since 节目库 shows them as failed.
 */
export async function pollWatchedFullVersions(): Promise<WatchedFullVersion[]> {
  const watched = readWatchedFullVersions();
  if (!watched.length) return [];
  let statuses: FullVersionItem[];
  try {
    statuses = await api.fullVersionStatuses(watched.map((item) => item.episodeId));
  } catch {
    return [];
  }
  const state = new Map<string, FullVersionState>(statuses.map((item) => [item.episode_id, item.status]));
  const finished = watched.filter((item) => state.get(item.episodeId) === "ready");
  // An episode the server no longer knows (or that never started) is dropped too.
  const settled = new Set(watched.filter((item) => {
    const status = state.get(item.episodeId);
    return status === undefined || status === "ready" || status === "failed" || status === "none";
  }).map((item) => item.episodeId));
  if (settled.size) write(WATCH_KEY, read(WATCH_KEY).filter((item) => !settled.has(item.episodeId)));
  if (finished.length) {
    const unseen = read(UNSEEN_KEY).filter((item) => !finished.some((done) => done.episodeId === item.episodeId));
    write(UNSEEN_KEY, [...unseen, ...finished]);
  }
  return finished;
}

/** Ask for the 完整版 of an episode being listened to, and keep an eye on it from now on. */
export async function requestFullVersion(episodeId: string, programmeId: string, title: string): Promise<void> {
  await api.materialize(episodeId);
  watchFullVersion({ episodeId, programmeId, title });
}

/** What the player shows for the programme it is playing: asked for / being prepared here, or already so on the server. */
export function playerFullVersion(
  episode: Pick<LiveEpisode, "state" | "generation_mode"> | null,
  saved: boolean,
  requesting: boolean,
): "none" | "preparing" | "ready" {
  if (saved || episode?.state === "MATERIALIZED" || episode?.state === "PUBLISHED") return "ready";
  return requesting || episode?.generation_mode === "FULL" ? "preparing" : "none";
}
