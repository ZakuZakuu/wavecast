// "少放这类" has no API in P0: record locally so P1 can upload it later.
const LESS_KEY = "wavecast-less-like-this-v1";
const CAPTIONS_KEY = "wavecast-captions-v1";

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

export function readCaptionsEnabled(): boolean {
  if (typeof window === "undefined") return true;
  try {
    return window.localStorage.getItem(CAPTIONS_KEY) !== "off";
  } catch {
    return true;
  }
}

export function writeCaptionsEnabled(enabled: boolean): void {
  try {
    window.localStorage.setItem(CAPTIONS_KEY, enabled ? "on" : "off");
  } catch {
    // Best effort only.
  }
}
