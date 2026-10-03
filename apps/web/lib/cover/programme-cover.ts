// Derives the one set of cover params used everywhere for a programme.
import { stationById, type CoverTemplate, type StationId } from "../stations";
import { buildCover, visualLength, type CoverParams } from "./build-cover";

export const MAX_HEADING_WIDTH = 10;

/** FNV-1a hash of the programme id, folded into 0..9972 (as CoverVariety). */
export function seedFromId(id: string): number {
  let hash = 0x811c9dc5;
  for (let index = 0; index < id.length; index += 1) {
    hash ^= id.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0) % 9973;
}

/**
 * Cover short title (HANDOFF §7): the part of the title before the first colon
 * or comma. Returns null when it is still visually wider than 10, in which case
 * the cover is drawn bare and the title is shown beneath it.
 */
export function coverHeading(title: string): string | null {
  // A hyphen inside a word (Lo-fi, Trip-hop) is not a separator; " - " is.
  const head = title.split(/[:：,，、;；|｜—–]|\s-\s/)[0]?.trim() ?? "";
  const text = head || title.trim();
  if (!text) return null;
  if (visualLength(text) > MAX_HEADING_WIDTH) return null;
  return breakHeading(text);
}

/** Allows at most one line break, near the visual middle, for headings wider than 5. */
export function breakHeading(text: string): string {
  if (visualLength(text) <= 5) return text;
  const chars = [...text];
  const spaceIndex = chars.findIndex((ch, index) => ch === " " && index > 0 && index < chars.length - 1);
  if (spaceIndex > 0) {
    const left = chars.slice(0, spaceIndex).join("");
    const right = chars.slice(spaceIndex + 1).join("");
    if (visualLength(left) <= 6 && visualLength(right) <= 6) return left + "\n" + right;
  }
  const total = visualLength(text);
  let running = 0;
  let best = 1;
  let bestDistance = Infinity;
  for (let index = 1; index < chars.length; index += 1) {
    running += visualLength(chars[index - 1]);
    // Never split inside a latin word.
    if (/[A-Za-z0-9]/.test(chars[index - 1]) && /[A-Za-z0-9]/.test(chars[index])) continue;
    const distance = Math.abs(running - total / 2);
    if (distance < bestDistance) {
      bestDistance = distance;
      best = index;
    }
  }
  return (chars.slice(0, best).join("").trimEnd() + "\n" + chars.slice(best).join("").trimStart());
}

export type ProgrammeCover = {
  params: CoverParams;
  /** Template and background the seed resolved to (for theming around the cover). */
  template: CoverTemplate;
  bg: string;
  /** True when the title did not fit the cover; render it beneath the cover. */
  titleBelow: boolean;
};

// --- Cover identity for programmes created from a card (featured promise,
// recommendation): the new programme keeps the card's cover seed, so the
// cover the listener clicked is the one they see in the player and library.

const COVER_ALIAS_KEY = "wavecast-cover-alias-v1";

function readCoverAliases(): Record<string, string> {
  if (typeof window === "undefined") return {};
  try {
    const parsed = JSON.parse(window.localStorage.getItem(COVER_ALIAS_KEY) ?? "{}");
    return parsed && typeof parsed === "object" ? parsed as Record<string, string> : {};
  } catch {
    return {};
  }
}

export function rememberCoverSource(programmeId: string, coverId: string): void {
  if (typeof window === "undefined" || programmeId === coverId) return;
  try {
    const map = readCoverAliases();
    map[programmeId] = coverId;
    const entries = Object.entries(map).slice(-200);
    window.localStorage.setItem(COVER_ALIAS_KEY, JSON.stringify(Object.fromEntries(entries)));
  } catch {
    // Storage is a convenience; the programme id still seeds a stable cover.
  }
}

/** The id that seeds a programme's cover: the card it came from, else itself. */
export function coverIdFor(programmeId: string): string {
  return readCoverAliases()[programmeId] ?? programmeId;
}

export function programmeCover(input: {
  id: string;
  title: string;
  stationId: StationId;
}): ProgrammeCover {
  const heading = coverHeading(input.title);
  const params: CoverParams = {
    stationId: stationById(input.stationId).id,
    seed: seedFromId(coverIdFor(input.id)),
    heading: heading ?? "",
    bare: heading === null,
  };
  const built = buildCover(params);
  return { params, template: built.template, bg: built.bg, titleBelow: heading === null };
}
