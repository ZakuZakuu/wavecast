// The picture each station carries on the tuner card: one fixed cover per station, in the same flat style as the
// programme covers, cropped or inset so that nothing is cut by the card's rounded corners. The numbers were chosen
// on the design canvas (调频改版) and are the same covers the app draws everywhere else.
import type { CoverPin } from "./cover/styled/types";
import type { StationId } from "./stations";

export type PosterSpec = {
  seed: number;
  pin: CoverPin;
  /** Zoom into part of the cover: `scale`× around the cover's (cx, cy), which lands at (px, py) of the poster. */
  crop?: { scale: number; cx: number; cy: number; px: number; py: number };
  /** Plain scale about the centre (a little over 1 hides the cover's own edge; under 1 leaves a margin). */
  scale?: number;
};

export const STATION_POSTERS: Record<StationId, PosterSpec> = {
  // A tuner dial, cropped so its quarter-circle sits low-left and half of it leaves the picture.
  casual: { seed: 3, pin: { style: "scene", motif: "tuner", layout: 0 }, crop: { scale: 1.8, cx: 0.5, cy: 0.75, px: 0.3, py: 0.95 } },
  crate: { seed: 3, pin: { style: "sleeve", motif: "cassette", layout: 0 }, scale: 1.03 },
  // Piano keys with a margin all round, so the keys are not cut by the corners.
  portrait: { seed: 4, pin: { style: "sleeve", motif: "keys", layout: 0 }, scale: 0.9 },
  // A part of the concentric contour lines, its centre a little up and to the right.
  lineage: { seed: 10, pin: { style: "blue", motif: "contour", layout: 0 }, crop: { scale: 1.8, cx: 0.54, cy: 0.48, px: 0.57, py: 0.43 } },
  night: { seed: 1, pin: { style: "glow", motif: "moon", layout: 0 }, scale: 1.03 },
};

/** The CSS transform of the cover inside its poster frame. */
export function posterTransform(spec: PosterSpec): { transform: string; transformOrigin: string } {
  if (spec.crop) {
    const { scale, cx, cy, px, py } = spec.crop;
    return { transform: `translate(${(px - scale * cx) * 100}%, ${(py - scale * cy) * 100}%) scale(${scale})`, transformOrigin: "0 0" };
  }
  return { transform: `scale(${spec.scale ?? 1})`, transformOrigin: "50% 50%" };
}
