// "少放这类": kept on this device, and sent to the account's preferences once signed in, where
// the recommendations read it. Tuned programmes get the same artists through taste_context.
const LESS_KEY = "wavecast-less-like-this-v1";

export type LessLikeThis = { trackRef: string; title: string; artist: string | null; episodeId: string; at: number };

export function readLessLikeThis(): LessLikeThis[] {
  if (typeof window === "undefined") return [];
  try {
    const parsed = JSON.parse(window.localStorage.getItem(LESS_KEY) ?? "[]");
    return Array.isArray(parsed) ? parsed as LessLikeThis[] : [];
  } catch {
    return [];
  }
}

export function recordLessLikeThis(entry: Omit<LessLikeThis, "at">): void {
  if (typeof window === "undefined") return;
  try {
    const next = [{ ...entry, at: Date.now() }, ...readLessLikeThis().filter((item) => item.trackRef !== entry.trackRef)];
    window.localStorage.setItem(LESS_KEY, JSON.stringify(next.slice(0, 100)));
  } catch {
    // Best effort only.
  }
}

/** Forgets an artist on this device (the account's list is changed through the API). */
export function removeLessLikeThisArtist(artist: string): void {
  if (typeof window === "undefined") return;
  try {
    const name = artist.trim().toLowerCase();
    const kept = readLessLikeThis().filter((item) => item.artist?.trim().toLowerCase() !== name);
    window.localStorage.setItem(LESS_KEY, JSON.stringify(kept));
  } catch {
    // Best effort only.
  }
}

/** Artists the listener asked to hear less of, newest first, without repeats. */
export function lessLikeThisArtists(): string[] {
  const seen = new Set<string>();
  const names: string[] = [];
  for (const entry of readLessLikeThis()) {
    const name = entry.artist?.trim();
    if (!name || seen.has(name.toLowerCase())) continue;
    seen.add(name.toLowerCase());
    names.push(name);
  }
  return names;
}

const SYNCED_KEY = "wavecast-less-like-this-synced-v1";

function readSynced(userId: string): string[] {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(SYNCED_KEY + ":" + userId) ?? "[]");
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === "string") : [];
  } catch {
    return [];
  }
}

/**
 * Sends the artists marked on this device to the account, once each. Called on sign-in so what a
 * guest marked before logging in is not lost; failures are retried the next time.
 */
export async function syncLessLikeThis(
  userId: string,
  send: (artist: string, userId: string) => Promise<unknown>,
): Promise<void> {
  const done = new Set(readSynced(userId));
  // Oldest first, so the newest ends up first in the account's list.
  for (const name of lessLikeThisArtists().reverse()) {
    if (done.has(name.toLowerCase())) continue;
    try {
      await send(name, userId);
    } catch {
      return;
    }
    done.add(name.toLowerCase());
    try {
      window.localStorage.setItem(SYNCED_KEY + ":" + userId, JSON.stringify([...done].slice(-100)));
    } catch {
      // Sent already; at worst the artist is sent again next time, which the server deduplicates.
    }
  }
}
