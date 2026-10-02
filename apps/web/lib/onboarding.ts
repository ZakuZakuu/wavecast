// First-run taste onboarding: mapping UI choices onto the backend schema.
import type { UserGenre, UserPreferences, UserPreferencesUpdate } from "./types";

export const ONBOARDING_GENRES = [
  "华语流行", "R&B", "爵士", "City Pop", "电子", "民谣",
  "摇滚", "独立", "Hip-hop", "古典", "氛围", "原声带",
] as const;

export const ONBOARDING_MOMENTS = ["通勤", "工作", "运动", "做饭", "开车", "睡前"] as const;

/** Backend genre enum covers only part of the design's list. */
const GENRE_MAP: Partial<Record<string, UserGenre>> = {
  "R&B": "R&B",
  "爵士": "Jazz",
  "City Pop": "City Pop",
  "电子": "Electronic",
  "Hip-hop": "Hip-Hop",
  "摇滚": "Rock",
  "古典": "Classical",
};

export function backendGenres(genres: readonly string[]): UserGenre[] {
  return Array.from(new Set(genres.map((genre) => GENRE_MAP[genre]).filter((genre): genre is UserGenre => Boolean(genre))));
}

export function parseArtists(text: string): string[] {
  return Array.from(new Set(
    text.split(/[、,，;；/\n]+/).map((item) => item.trim()).filter(Boolean).map((item) => item.slice(0, 80)),
  )).slice(0, 20);
}

export function preferenceUpdate(
  existing: UserPreferences | null,
  choice: { genres: readonly string[]; artists: string; moments: readonly string[] } | null,
): UserPreferencesUpdate {
  return {
    genres: choice ? backendGenres(choice.genres) : existing?.genres ?? [],
    artists: choice ? parseArtists(choice.artists) : existing?.artists ?? [],
    moods: existing?.moods ?? [],
    contexts: choice ? [...choice.moments].slice(0, 20) : existing?.contexts ?? [],
    discovery_level: existing?.discovery_level ?? "BALANCED",
    onboarding_completed: true,
  };
}

const doneKey = (userId: string) => `wavecast-onboarding-done:${userId}`;

export function onboardingDoneLocally(userId: string): boolean {
  try {
    return window.localStorage.getItem(doneKey(userId)) === "1";
  } catch {
    return false;
  }
}

export function markOnboardingDoneLocally(userId: string): void {
  try {
    window.localStorage.setItem(doneKey(userId), "1");
  } catch {
    // Best effort only.
  }
}
