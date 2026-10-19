// Which cover a programme gets. Nothing is stored: station and seed (from the programme id) decide it, so every
// surface draws the same one. Changing a list or a share below changes every programme's cover; bump the version.
import { rng } from "../build-cover";
import type { StationId } from "../../stations";
import { hashString } from "./color";
import { LAYOUT_COUNTS } from "./styles";
import { COVER_MOTIFS, COVER_STYLES, type CoverMotif, type CoverPin, type CoverStyle, type Rng, type StyledCoverStyle } from "./types";

export const COVER_SELECTION_VERSION = 1;

/** Styles each station leans on. */
export const STYLE_FAVOURITES: Record<StationId, StyledCoverStyle[]> = {
  casual: ["scene", "cut", "line"],
  crate: ["sleeve", "riso", "poster"],
  portrait: ["poster", "sleeve", "line"],
  lineage: ["blue", "line", "poster"],
  night: ["neon", "glow", "scene"],
};

/** Pictures that suit each station. */
export const MOTIF_POOLS: Record<StationId, CoverMotif[]> = {
  casual: ["rain", "road", "headphones", "tuner", "rays", "plant", "sea", "mountains", "forest", "cassette"],
  crate: ["vinyl", "cassette", "bars", "keys", "strings", "headphones", "tuner", "ripples", "mic"],
  portrait: ["keys", "strings", "mic", "vinyl", "headphones", "cassette", "skyline", "contour", "plant"],
  lineage: ["contour", "sea", "mountains", "skyline", "road", "forest", "windows", "vinyl", "rays", "tuner"],
  night: ["moon", "windows", "skyline", "ripples", "forest", "sea", "mountains", "headphones", "vinyl", "tuner"],
};

/** Odds: a station's favourite style, the original cover, else any style (the original is not drawn here). */
const FAVOURITE_SHARE = 0.6;
const LEGACY_SHARE = 0.1;
/** Odds that the picture comes from the station's pool rather than from all of them. */
const POOL_SHARE = 0.85;

const STYLED = COVER_STYLES.filter((style): style is StyledCoverStyle => style !== "legacy");
const pick = <T>(items: readonly T[], random: Rng): T => items[Math.floor(random() * items.length)];

export type CoverChoice = { style: CoverStyle; motif: CoverMotif; layout: number };

export function selectCover(stationId: StationId, seed: number, pin?: CoverPin): CoverChoice {
  const random = rng(hashString(`wavecast-cover:${COVER_SELECTION_VERSION}:${stationId}:${seed}`));
  const roll = random();
  const derived: CoverStyle = roll < FAVOURITE_SHARE
    ? pick(STYLE_FAVOURITES[stationId], random)
    : roll < FAVOURITE_SHARE + LEGACY_SHARE ? "legacy" : pick(STYLED, random);
  const motif = pin?.motif ?? pick(random() < POOL_SHARE ? MOTIF_POOLS[stationId] : COVER_MOTIFS, random);
  const style = pin?.style ?? derived;
  const layoutRoll = random();
  const count = style === "legacy" ? 1 : LAYOUT_COUNTS[style];
  return { style, motif, layout: pin?.layout ?? Math.floor(layoutRoll * count) };
}
