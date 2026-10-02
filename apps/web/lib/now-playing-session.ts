// Persists the current playback session so a reclaimed/reloaded page (iOS
// PWA in the background) can restore the mini player in a paused state.

export const SESSION_KEY = "wavecast-now-playing-v1";
export const SESSION_MAX_AGE_MS = 12 * 60 * 60 * 1000;
/** Must match the hook's listener checkpoint key (lib/use-programme-playback.ts). */
const PROGRESS_PREFIX = "wavecast-program-progress:";

export type NowPlayingSession = {
  target: { seedId?: string; episodeId: string };
  positionSeconds: number;
  playing: boolean;
  updatedAt: number;
};

function storage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

function isSession(value: unknown): value is NowPlayingSession {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<NowPlayingSession>;
  return Boolean(
    candidate.target
    && typeof candidate.target.episodeId === "string"
    && candidate.target.episodeId.length > 0
    && typeof candidate.positionSeconds === "number"
    && Number.isFinite(candidate.positionSeconds)
    && candidate.positionSeconds >= 0
    && typeof candidate.playing === "boolean"
    && typeof candidate.updatedAt === "number",
  );
}

export function isSessionFresh(session: NowPlayingSession, now = Date.now()): boolean {
  return now - session.updatedAt <= SESSION_MAX_AGE_MS && session.updatedAt <= now + 60_000;
}

/** The stored session, or null when missing, malformed or older than 12 hours. */
export function readNowPlayingSession(now = Date.now(), store = storage()): NowPlayingSession | null {
  if (!store) return null;
  try {
    const parsed: unknown = JSON.parse(store.getItem(SESSION_KEY) ?? "null");
    if (!isSession(parsed)) return null;
    if (!isSessionFresh(parsed, now)) {
      store.removeItem(SESSION_KEY);
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

export function writeNowPlayingSession(
  session: Omit<NowPlayingSession, "updatedAt">,
  now = Date.now(),
  store = storage(),
): void {
  if (!store) return;
  try {
    const value: NowPlayingSession = {
      target: { episodeId: session.target.episodeId, ...(session.target.seedId ? { seedId: session.target.seedId } : {}) },
      positionSeconds: Math.max(0, session.positionSeconds),
      playing: session.playing,
      updatedAt: now,
    };
    store.setItem(SESSION_KEY, JSON.stringify(value));
  } catch {
    // Storage full or blocked: restoring is best effort.
  }
}

export function clearNowPlayingSession(store = storage()): void {
  try {
    store?.removeItem(SESSION_KEY);
  } catch {
    // Ignore.
  }
}

/**
 * Restore position: the local record, unless the server saw newer activity
 * (another device) with a meaningfully different checkpoint.
 */
export function restorePosition(
  session: NowPlayingSession,
  server: { positionSeconds: number; lastActivityAt: number | null } | null,
): number {
  if (
    server
    && server.lastActivityAt !== null
    && server.lastActivityAt > session.updatedAt + 2_000
    && Math.abs(server.positionSeconds - session.positionSeconds) > 3
  ) {
    return Math.max(0, server.positionSeconds);
  }
  return session.positionSeconds;
}

/**
 * Seeds the playback hook's own checkpoint so the restored host boots paused
 * at `positionSeconds` (continueWhileHidden=false: never resume audibly
 * without a user gesture).
 */
export function primePausedProgress(episodeId: string, positionSeconds: number, now = Date.now(), store = storage()): void {
  try {
    store?.setItem(PROGRESS_PREFIX + episodeId, JSON.stringify({
      positionSeconds: Math.max(0, positionSeconds),
      updatedAtMs: now,
      continueWhileHidden: false,
    }));
  } catch {
    // Ignore.
  }
}
