// Needle position during the cold open: 107 → 88.7, decelerating into each
// station, a ~0.25 s dwell on it, then a damped wobble on the 88.7 lock.
import { COLD } from "../timeline";
import { lerp, p, sine } from "../lib/math";

const DWELL = 0.25;
// [target freq, travel seconds]
const LEGS: Array<[number, number]> = [
  [105.8, 0.45],
  [101.5, 0.85],
  [97.4, 0.85],
  [93.1, 0.85],
  [88.7, 1.0],
];

type Stop = { t0: number; t1: number; from: number; to: number; dwellEnd: number };
const STOPS: Stop[] = (() => {
  const out: Stop[] = [];
  let t = COLD.sweep[0];
  let f = COLD.startFreq;
  LEGS.forEach(([to, dur], i) => {
    const last = i === LEGS.length - 1;
    out.push({ t0: t, t1: t + dur, from: f, to, dwellEnd: last ? t + dur : t + dur + DWELL });
    t = last ? t + dur : t + dur + DWELL;
    f = to;
  });
  return out;
})();

/** Station arrival times (for glows, names and the chord stabs). */
export const STATION_HITS = STOPS.map((s) => ({ freq: s.to, at: s.t1, until: s.dwellEnd }));

export function coldFreq(t: number): number {
  if (t <= STOPS[0].t0) return COLD.startFreq;
  for (const s of STOPS) {
    if (t < s.t1) return lerp(s.from, s.to, sine(p(t, s.t0, s.t1)));
    if (t < s.dwellEnd) return s.to;
  }
  // Lock wobble: continues leftwards, swings back two or three times, settles by 6.6.
  const x = t - COLD.lock[0];
  if (x > 0.6) return COLD.lockFreq;
  return COLD.lockFreq - 0.32 * Math.exp(-x / 0.14) * Math.sin(x * Math.PI * 2 * 4.2) * (1 - p(t, 6.45, 6.6));
}
