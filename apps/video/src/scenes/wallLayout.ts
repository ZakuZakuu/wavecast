// Cover-wall layout and timing, shared by the picture (Wall.tsx) and the
// sound (one note per cover). Pure: no React, no fonts.
import { WALL_TITLES } from "../content";
import { rng } from "../lib/math";
import { NEXT } from "../timeline";

const COLS = 9;
const ROWS = 6;
const PITCH = 200;

/** 9 × 6 grid around the phone (two middle cells) minus the disclaimer corner: 50 covers. */
export const TILES = (() => {
  const R = rng(2468);
  const out: Array<{ x: number; y: number; d: number; station: (typeof WALL_TITLES)[number][0]; heading: string; seed: number; jitter: number }> = [];
  let k = 0;
  for (let r = 0; r < ROWS; r++) {
    for (let c = 0; c < COLS; c++) {
      if (c === 4 && (r === 2 || r === 3)) continue;
      // Keep the bottom-right corner clear for the disclaimer.
      if (r === ROWS - 1 && c >= COLS - 2) continue;
      const x = 960 + (c - 4) * PITCH;
      const y = 540 + (r - 2.5) * PITCH;
      const d = Math.hypot((x - 960) / PITCH, (y - 540) / PITCH);
      out.push({ x, y, d, station: "casual", heading: "", seed: 0, jitter: R() * 0.25 });
      k++;
    }
  }
  // Titles are dealt out so neighbours differ; every tile gets its own seed.
  const order = out.map((_, i) => i).sort((a, b) => (a * 7919) % 53 - (b * 7919) % 53);
  order.forEach((tileIdx, n) => {
    const [station, heading] = WALL_TITLES[n % WALL_TITLES.length];
    out[tileIdx].station = station;
    out[tileIdx].heading = heading;
    out[tileIdx].seed = 300 + n * 37 + Math.floor(n / WALL_TITLES.length) * 11;
  });
  return out;
})();

/** When a tile appears: waves from the centre outwards. */
export const tileAppearAt = (tile: { d: number; jitter: number }) => NEXT.wall[0] + 0.5 + tile.d * 0.42 + tile.jitter;
