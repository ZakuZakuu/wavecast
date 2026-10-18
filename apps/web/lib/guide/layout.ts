// Where the guide card goes next to the lit element. Pure geometry, in viewport pixels.
export type Box = { left: number; top: number; width: number; height: number };

export const SPOT_PAD = 6;
const GAP = 14;
const EDGE = 16;
/** Room the card needs on one side (a bit above its tallest content). */
const ROOM = 200;
export const BUBBLE_WIDTH = 310;

export type Placement = {
  side: "above" | "below" | "center";
  left: number;
  /** Distance from the top (below / center) or from the bottom (above) of the viewport. */
  edge: number;
  /** Arrow position inside the card. */
  arrow: number;
  width: number;
};

export function placeBubble(
  target: Box | null,
  viewport: { width: number; height: number },
  side: "above" | "below" = "below",
): Placement {
  const width = Math.min(BUBBLE_WIDTH, viewport.width - EDGE * 2);
  if (!target) {
    return { side: "center", left: (viewport.width - width) / 2, edge: Math.max(EDGE, viewport.height * 0.34), arrow: 0, width };
  }
  const centre = target.left + target.width / 2;
  const left = Math.max(EDGE, Math.min(viewport.width - EDGE - width, centre - width / 2));
  const above = target.top - SPOT_PAD - GAP;
  const below = viewport.height - (target.top + target.height + SPOT_PAD + GAP);
  const placed = side === "above"
    ? (above >= ROOM || above >= below ? "above" : "below")
    : (below >= ROOM || below >= above ? "below" : "above");
  return {
    side: placed,
    left,
    edge: placed === "below" ? target.top + target.height + SPOT_PAD + GAP : viewport.height - (target.top - SPOT_PAD - GAP),
    arrow: Math.max(22, Math.min(width - 38, centre - left - 8)),
    width,
  };
}
