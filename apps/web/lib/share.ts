// Programme links: /program/<id>. The link carries the promise (title, outline), never the
// audio; whoever opens it gets their own copy made when they press play.
import { coverIdFor } from "./cover/programme-cover";

/** The address people paste. `c` keeps a card's cover identical for the person who opens it. */
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

// A visitor who already made their copy of a link should not spend a second slot.
const ADOPTED_KEY = "wavecast-adopted-v1";

function readAdopted(): Record<string, string> {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(ADOPTED_KEY) ?? "{}");
    return parsed && typeof parsed === "object" ? parsed as Record<string, string> : {};
  } catch {
    return {};
  }
}

export function adoptedCopyOf(programmeId: string): string | null {
  if (typeof window === "undefined") return null;
  return readAdopted()[programmeId] ?? null;
}

export function rememberAdoptedCopy(programmeId: string, copyId: string): void {
  try {
    const map = readAdopted();
    map[programmeId] = copyId;
    window.localStorage.setItem(ADOPTED_KEY, JSON.stringify(Object.fromEntries(Object.entries(map).slice(-100))));
  } catch {
    // The server returns the same copy for the owner anyway; this only saves a round trip.
  }
}
