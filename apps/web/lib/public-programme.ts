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

/** The programme id behind a short link, or null when the code matches none. */
export async function resolveShortCode(code: string): Promise<string | null> {
  try {
    const response = await fetch(`${internalApiUrl}/api/programs/by-code/${encodeURIComponent(code)}`, {
      next: { revalidate: 300 },
    });
    if (!response.ok) return null;
    return ((await response.json()) as { id: string }).id;
  } catch {
    return null;
  }
}
