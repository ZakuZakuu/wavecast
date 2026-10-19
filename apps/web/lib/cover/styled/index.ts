import { bareCoverSvg, rng, type CoverParams } from "../build-cover";
import { formatFreq, stationById } from "../../stations";
import { hashString } from "./color";
import { MOTIFS } from "./motifs";
import { selectCover } from "./select";
import { STYLE_FNS } from "./styles";
import { coverViewToSvg } from "./svg";
import type { CoverView, StyledCoverStyle } from "./types";

export type ComposedCover = { kind: "legacy" } | { kind: "styled"; style: StyledCoverStyle; view: CoverView };

/** The cover for a programme: the original generator, or a styled one (picture, style and layout from station and seed). */
export function composeCover(params: CoverParams): ComposedCover {
  const choice = selectCover(params.stationId, params.seed, params.pin);
  if (choice.style === "legacy") return { kind: "legacy" };
  const station = stationById(params.stationId);
  // One random stream per cover: first the picture, then the style's palette and choices.
  const random = rng(hashString(`${choice.style}:${station.id}:${choice.motif}:${params.heading}`) + params.seed * 2654435761);
  const motif = MOTIFS[choice.motif](random);
  const view = STYLE_FNS[choice.style](motif, random, {
    heading: params.heading,
    layout: choice.layout,
    bare: Boolean(params.bare),
    station: { hue: station.cover.hue, name: station.name, freq: formatFreq(station.freq) },
  });
  return { kind: "styled", style: choice.style, view };
}

/** The cover as a standalone SVG without text or grain, for share previews and lock-screen artwork. */
export function coverSvg(params: CoverParams, size = 512): string {
  const composed = composeCover({ ...params, bare: true });
  return composed.kind === "styled" ? coverViewToSvg(composed.view, size) : bareCoverSvg(params, size);
}

export { COVER_MOTIFS, COVER_STYLES, type CoverMotif, type CoverPin, type CoverStyle } from "./types";
