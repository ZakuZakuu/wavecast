import type { Rng } from "./types";

/**
 * The station's hue with a little jitter, and an accent hue: mostly a neighbour, sometimes the opposite,
 * so a station keeps its colour family without being locked to one palette.
 */
const SHIFTS = [28, -28, 55, -55, 40, -40, 70, -70, 150, -150];
export function hues(stationHue: number, random: Rng): { h: number; ha: number } {
  const h = stationHue + (random() * 2 - 1) * 14;
  const ha = h + SHIFTS[Math.floor(random() * SHIFTS.length)] + (random() * 2 - 1) * 10;
  return { h, ha };
}
