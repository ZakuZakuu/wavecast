// Account page helpers (pure, tested).
import type { LocalTaste } from "./taste";
import type { UserLibraryState } from "./user-library";

export type AuthAvailability = { enabled: boolean; providers: string[]; emailOtp?: boolean };
export type SocialProvider = "github" | "google";

/** Sign-in buttons to show, GitHub first (as designed); none when sign-in is off. */
export function signInProviders(availability: AuthAvailability | null): SocialProvider[] {
  if (!availability?.enabled) return [];
  return (["github", "google"] as const).filter((provider) => availability.providers.includes(provider));
}

export function providerLabel(providerId: string | null | undefined): string | null {
  if (providerId === "github") return "通过 GitHub 登录";
  if (providerId === "google") return "通过 Google 登录";
  return null;
}

/** "R&B、爵士、City Pop" — genres first, then artists; null when unset. */
export function tasteSummary(taste: LocalTaste | null): string | null {
  if (!taste) return null;
  const parts = [...taste.genres];
  const artists = taste.artists.trim();
  if (artists) parts.push(artists);
  const text = parts.join("、");
  if (!text) return null;
  return text.length > 24 ? text.slice(0, 23) + "…" : text;
}

/** Distinct programmes in the library (listened, saved or created). */
export function libraryProgrammeCount(library: UserLibraryState): number {
  const ids = new Set<string>();
  for (const record of library.recentPrograms) ids.add(record.seedId);
  for (const record of library.savedEpisodes) ids.add(record.seedId);
  for (const id of library.createdProgramIds) ids.add(id);
  return ids.size;
}

export function avatarInitial(name: string | null | undefined, email: string | null | undefined): string {
  return name?.trim().slice(0, 1).toUpperCase() || email?.trim().slice(0, 1).toUpperCase() || "W";
}
