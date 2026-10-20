/**
 * What the home page last showed, kept so coming back to it shows cards at once and the fresh answer
 * quietly replaces them (stale-while-revalidate). Held in memory for in-app navigation and in
 * localStorage for a cold start; both are only a convenience, so every access is allowed to fail.
 */

const PREFIX = "wavecast:home:";
const memory = new Map<string, unknown>();
const inflight = new Map<string, Promise<unknown>>();

export function readHomeCache<T>(key: string): T | null {
  if (memory.has(key)) return memory.get(key) as T;
  try {
    const raw = window.localStorage.getItem(PREFIX + key);
    if (raw === null) return null;
    const value = JSON.parse(raw) as T;
    memory.set(key, value);
    return value;
  } catch {
    return null;
  }
}

export function writeHomeCache<T>(key: string, value: T): void {
  memory.set(key, value);
  try {
    window.localStorage.setItem(PREFIX + key, JSON.stringify(value));
  } catch {
    // Private mode or a full quota: the in-memory copy still serves this visit.
  }
}

export function clearHomeCache(key: string): void {
  memory.delete(key);
  try {
    window.localStorage.removeItem(PREFIX + key);
  } catch {
    // Nothing stored that could be removed.
  }
}

/** One request at a time per key: a quick second visit joins the one already on its way. */
export function sharedRequest<T>(key: string, start: () => Promise<T>): Promise<T> {
  const running = inflight.get(key) as Promise<T> | undefined;
  if (running) return running;
  const made = start().finally(() => inflight.delete(key));
  inflight.set(key, made);
  return made;
}

/** Who was signed in last: lets the home page show their cards while the session is still checked. */
export const LAST_USER_KEY = "last-user";

/** Forget everything held in memory (tests start each case from nothing). */
export function resetHomeCache(): void {
  memory.clear();
  inflight.clear();
}
