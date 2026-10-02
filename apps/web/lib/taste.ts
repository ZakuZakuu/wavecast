// Local listening preferences (onboarding). The backend preference schema
// only knows a subset of genres, so the full answer is also sent as
// taste_context text with proposal requests.
export type LocalTaste = {
  genres: string[];
  artists: string;
  moments: string[];
  updatedAt: number;
};

const KEY = "wavecast-taste-v1";

export function readLocalTaste(): LocalTaste | null {
  if (typeof window === "undefined") return null;
  try {
    const parsed = JSON.parse(window.localStorage.getItem(KEY) ?? "null") as LocalTaste | null;
    if (!parsed || !Array.isArray(parsed.genres)) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function writeLocalTaste(taste: Omit<LocalTaste, "updatedAt">): void {
  try {
    window.localStorage.setItem(KEY, JSON.stringify({ ...taste, updatedAt: Date.now() }));
  } catch {
    // Best effort only.
  }
}

/** Compact, bounded text for ProposalGenerationRequest.taste_context (≤1000). */
export function tasteContext(taste: LocalTaste | null): string | undefined {
  if (!taste) return undefined;
  const parts: string[] = [];
  if (taste.genres.length) parts.push("爱听：" + taste.genres.join("、"));
  if (taste.artists.trim()) parts.push("喜欢的歌手：" + taste.artists.trim());
  if (taste.moments.length) parts.push("常在这些时候听：" + taste.moments.join("、"));
  const text = parts.join("；");
  return text ? text.slice(0, 1000) : undefined;
}
