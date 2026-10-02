// Derives the one set of cover params used everywhere for a programme.
import { formatFreq, stationById, type Station, type StationId } from "../stations";
import { visualLength, type CoverParams } from "./build-cover";

export const MAX_HEADING_WIDTH = 10;

/** FNV-1a hash of the programme id, folded into 0..999. */
export function seedFromId(id: string): number {
  let hash = 0x811c9dc5;
  for (let index = 0; index < id.length; index += 1) {
    hash ^= id.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0) % 1000;
}

/**
 * Cover short title (HANDOFF §7): the part of the title before the first colon
 * or comma. Returns null when it is still visually wider than 10, in which case
 * the cover is drawn bare and the title is shown beneath it.
 */
export function coverHeading(title: string): string | null {
  const head = title.split(/[:：,，、;；|｜\-—–]/)[0]?.trim() ?? "";
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

export function templateForStation(station: Station, seed: number) {
  return station.templates[seed % station.templates.length];
}

export type ProgrammeCover = {
  params: CoverParams;
  /** True when the title did not fit the cover; render it beneath the cover. */
  titleBelow: boolean;
};

export function programmeCover(input: {
  id: string;
  title: string;
  stationId: StationId;
}): ProgrammeCover {
  const station = stationById(input.stationId);
  const seed = seedFromId(input.id);
  const template = templateForStation(station, seed);
  const palette = station.palettes[template]!;
  const heading = coverHeading(input.title);
  return {
    params: {
      template,
      seed,
      ...palette,
      heading: heading ?? "",
      station: station.name,
      freq: formatFreq(station.freq),
      bare: heading === null,
    },
    titleBelow: heading === null,
  };
}
