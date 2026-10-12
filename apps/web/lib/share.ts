// Programme links: /program/<id>. The link carries the promise (title, outline), never the
// audio; whoever opens it gets their own copy made when they press play.
import { coverIdFor } from "./cover/programme-cover";

const PROPOSAL_ID = /^proposal-([0-9a-f]{16,32})$/;

/** The first ten hex digits of a generated programme's id: what a short link carries. */
export function shortCodeFor(programmeId: string): string | null {
  const match = PROPOSAL_ID.exec(programmeId);
  return match ? match[1].slice(0, 10) : null;
}

/**
 * The address people paste: /p/<code> for generated programmes, /program/<id> for the built-in
 * ones. `c` keeps a card's cover identical for the person who opens it.
 */
export function programmeShareUrl(programmeId: string, origin?: string): string {
  const base = origin ?? (typeof window === "undefined" ? "" : window.location.origin);
  const cover = coverIdFor(programmeId);
  const query = cover !== programmeId ? `?c=${encodeURIComponent(cover)}` : "";
  const code = shortCodeFor(programmeId);
  return code ? `${base}/p/${code}${query}` : `${base}/program/${encodeURIComponent(programmeId)}${query}`;
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

// A visitor who already made their copy of a link should not spend a second slot. The copy
// belongs to one identity (an account, or this browser's guest), so the record is kept per
// identity and checked with the server before it is used again.
const ADOPTED_KEY = "wavecast-adopted-v2";
export const GUEST_IDENTITY = "guest";

function readAdopted(): Record<string, string> {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(ADOPTED_KEY) ?? "{}");
    return parsed && typeof parsed === "object" ? parsed as Record<string, string> : {};
  } catch {
    return {};
  }
}

function writeAdopted(map: Record<string, string>): void {
  try {
    window.localStorage.setItem(ADOPTED_KEY, JSON.stringify(Object.fromEntries(Object.entries(map).slice(-100))));
  } catch {
    // The server returns the same copy for the owner anyway; this only saves a round trip.
  }
}

const adoptedKey = (identity: string, programmeId: string) => `${identity}|${programmeId}`;

/**
 * Copies this identity may already hold of a shared programme, most likely first. A guest's copy
 * becomes the account's when they sign in, so the guest record is a candidate for an account too.
 */
export function adoptedCopies(programmeId: string, identity: string): string[] {
  if (typeof window === "undefined") return [];
  const map = readAdopted();
  const own = map[adoptedKey(identity, programmeId)];
  const guest = identity === GUEST_IDENTITY ? undefined : map[adoptedKey(GUEST_IDENTITY, programmeId)];
  return [own, guest].filter((id, index, list): id is string => Boolean(id) && list.indexOf(id) === index);
}

export function rememberAdoptedCopy(programmeId: string, copyId: string, identity: string): void {
  const map = readAdopted();
  map[adoptedKey(identity, programmeId)] = copyId;
  writeAdopted(map);
}

export function forgetAdoptedCopy(programmeId: string, copyId: string): void {
  const map = readAdopted();
  for (const key of Object.keys(map)) {
    if (key.endsWith("|" + programmeId) && map[key] === copyId) delete map[key];
  }
  writeAdopted(map);
}
