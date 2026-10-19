/** The album cover of the song that is playing, shown beside the programme's own cover. */

export type CoverFront = "song" | "show";

/** NetEase serves the same picture at any size when asked; the player never needs the original. */
const RESIZABLE_HOST = /(^|\.)music\.126\.net$/;
const SIZE_PARAM = "600y600";

/** The address to load for a cover the backend named, or null when it is not a usable web address. */
export function songCoverSrc(url: string | null | undefined): string | null {
  if (!url) return null;
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return null;
  }
  if (parsed.protocol !== "https:") return null;
  if (RESIZABLE_HOST.test(parsed.hostname)) parsed.searchParams.set("param", SIZE_PARAM);
  return parsed.toString();
}

/**
 * Which cover is in front. A choice the listener made is kept; otherwise the programme's cover
 * until the programme has started, then the song's, and the programme's whenever the song has
 * no cover to show.
 */
export function coverInFront({ choice, songReady, started }: {
  choice: CoverFront | null;
  songReady: boolean;
  started: boolean;
}): CoverFront {
  if (!songReady) return "show";
  if (choice) return choice;
  return started ? "song" : "show";
}

// The listener's last choice lasts for the visit: it carries to the next song and the next
// programme, and is gone on reload.
let remembered: CoverFront | null = null;

export function rememberedCoverChoice(): CoverFront | null {
  return remembered;
}

export function rememberCoverChoice(choice: CoverFront | null): void {
  remembered = choice;
}
