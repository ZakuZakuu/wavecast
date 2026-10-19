// Programme links. A generated programme is shared once it is published: /p/<code> opens the
// published programme itself, and whoever opens it plays the same audio with their own progress.
// A built-in programme has nothing to publish: its page is the link.
import { coverIdFor } from "./cover/programme-cover";

const PUBLICATION_ID = /^pub-([0-9a-f]{32})$/;
const SHORT_CODE_LENGTH = 10;

/** The first ten hex digits of a published programme's id: what its short link carries. */
export function publicationCode(publicationId: string): string | null {
  const match = PUBLICATION_ID.exec(publicationId);
  return match ? match[1].slice(0, SHORT_CODE_LENGTH) : null;
}

/** Whether a programme is a generated one, which is shared by publishing it. */
export function isGeneratedProgramme(programmeId: string): boolean {
  return programmeId.startsWith("proposal-");
}

/**
 * The address people paste for a published programme. Its cover is made from its own id, the same
 * for everyone who sees it (the home page, the link, the library), so the link carries no hint.
 */
export function publishedShareUrl(publicationId: string, origin?: string): string {
  const base = origin ?? (typeof window === "undefined" ? "" : window.location.origin);
  const code = publicationCode(publicationId);
  return code ? `${base}/p/${code}` : `${base}/program/${encodeURIComponent(publicationId)}`;
}

/** The page of a built-in programme. */
export function programmeShareUrl(programmeId: string, origin?: string): string {
  const base = origin ?? (typeof window === "undefined" ? "" : window.location.origin);
  const cover = coverIdFor(programmeId);
  const query = cover !== programmeId ? `?c=${encodeURIComponent(cover)}` : "";
  return `${base}/program/${encodeURIComponent(programmeId)}${query}`;
}

/** wavecast.space/program/… without the scheme, for the preview card. */
export function displayShareUrl(url: string): string {
  return url.replace(/^https?:\/\//, "");
}

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    try {
      const field = document.createElement("textarea");
      field.value = text;
      field.setAttribute("readonly", "");
      field.style.position = "fixed";
      field.style.opacity = "0";
      document.body.appendChild(field);
      field.select();
      const done = document.execCommand("copy");
      field.remove();
      return done;
    } catch {
      return false;
    }
  }
}

export function canNativeShare(): boolean {
  return typeof navigator !== "undefined" && typeof navigator.share === "function";
}

/** Opens the system share sheet; false when the person closed it or it is unavailable. */
export async function nativeShare(data: { title: string; text: string; url: string }): Promise<boolean> {
  if (!canNativeShare()) return false;
  try {
    await navigator.share(data);
    return true;
  } catch {
    return false;
  }
}
