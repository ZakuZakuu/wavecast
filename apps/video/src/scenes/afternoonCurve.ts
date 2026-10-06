// Afternoon tuner frequency: the finger drags 88.7 → 93.1 → 97.4 (through the
// gaps between stations), then the typed description slides it to 93.1.
import { AFTERNOON } from "../timeline";
import { eio, lerp, p, sine } from "../lib/math";

const [d0, d1] = AFTERNOON.drag;
const LEG1: [number, number] = [d0, d0 + 1.4];
const LEG2: [number, number] = [d0 + 1.9, d1 - 0.2];

const settle = (x: number, amp: number) => amp * Math.exp(-x / 0.18) * Math.sin(x * Math.PI * 2 * 3.2);

export function tuneFreq(t: number): number {
  if (t < LEG1[0]) return 88.7;
  if (t < LEG1[1]) return lerp(88.7, 93.1, eio(p(t, LEG1[0], LEG1[1])));
  if (t < LEG2[0]) return 93.1 + settle(t - LEG1[1], 0.12);
  if (t < LEG2[1]) return lerp(93.1, 97.4, eio(p(t, LEG2[0], LEG2[1])));
  const [a0, a1] = AFTERNOON.align;
  if (t < a0) return 97.4 + settle(t - LEG2[1], 0.12);
  if (t < a1) return lerp(97.4, 93.1, sine(p(t, a0, a1)));
  return 93.1 + settle(t - a1, 0.16);
}
