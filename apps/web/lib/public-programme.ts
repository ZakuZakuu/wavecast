// Server-side read of a programme link, for the page title and the preview image.
import type { PublicProgramme } from "./types";

const internalApiUrl = process.env.WAVECAST_INTERNAL_API_URL ?? "http://127.0.0.1:8000";

export async function fetchPublicProgramme(id: string): Promise<PublicProgramme | null> {
  try {
    const response = await fetch(`${internalApiUrl}/api/programs/${encodeURIComponent(id)}/public`, {
      next: { revalidate: 300 },
    });
    if (!response.ok) return null;
    return (await response.json()) as PublicProgramme;
  } catch {
    return null;
  }
}

export type ShortLink = { id: string } | { gone: "legacy" | "missing" };

/**
 * The published programme behind a short link. A link of the old kind (it asked every visitor for a
 * fresh copy) is told apart from one that never existed, so each can say so.
 */
export async function resolveShortLink(code: string): Promise<ShortLink> {
  try {
    const response = await fetch(`${internalApiUrl}/api/programs/by-code/${encodeURIComponent(code)}`, {
      next: { revalidate: 300 },
    });
    if (response.ok) return { id: ((await response.json()) as { id: string }).id };
    if (response.status === 410) return { gone: "legacy" };
    return { gone: "missing" };
  } catch {
    return { gone: "missing" };
  }
}

/** The programme id behind a short link, or null when the code matches none. */
export async function resolveShortCode(code: string): Promise<string | null> {
  const link = await resolveShortLink(code);
  return "id" in link ? link.id : null;
}
