// Choreography of the film, ported 1:1 from the sample's script
// (docs/design/film/wavecast-film.html). All times are in seconds.
import { content } from "./content";
import { eio, lerp, p } from "./lib/anim";

export const FPS = 30;
export const DURATION = 76;
export const WIDTH = 1920;
export const HEIGHT = 1080;

/** Dial frequency over time (the tune screen drag, then the prompt lock). */
export function tuneF(t: number) {
  if (t < 11) return 88.7;
  if (t < 14.6) return lerp(88.7, 101.7, eio(p(t, 11, 14.6)));
  if (t < 20.6) {
    const x = t - 14.6;
    return 101.5 + 0.2 * Math.exp(-x / 0.3) * Math.cos(x * 11);
  }
  if (t < 22.2) return lerp(101.5, 106.0, eio(p(t, 20.6, 22.2)));
  const x = t - 22.2;
  return 105.8 + 0.2 * Math.exp(-x / 0.25) * Math.cos(x * 12);
}

export const TYPE_START = 17.2;
export const TYPE_END = 20.2;
export const typed = (t: number) => Math.floor(p(t, TYPE_START, TYPE_END) * content.prompt.length);

/** Camera keys: [time, scale, focus x, focus y] in phone-screen coordinates. */
export const KEYS: Array<[number, number, number, number]> = [
  [0, 1, 205, 432], [9.6, 1, 205, 432], [10.4, 1.45, 205, 315], [15.6, 1.45, 205, 315], [16.4, 1, 205, 432],
  [34.6, 1, 205, 432], [35.6, 1.35, 205, 566], [42.6, 1.35, 205, 566], [43.4, 1.3, 205, 640], [49.2, 1.3, 205, 640], [50, 1, 205, 432],
];
export const RIG = { left: 975, top: 108 };
export const ANCHOR = { x: RIG.left + 205, y: RIG.top + 432 };

export function cam(t: number) {
  let k = 0;
  while (k < KEYS.length - 1 && t > KEYS[k + 1][0]) k++;
  const a = KEYS[k],
    b = KEYS[Math.min(k + 1, KEYS.length - 1)];
  const x = b[0] === a[0] ? 0 : eio(p(t, a[0], b[0]));
  return { s: lerp(a[1], b[1], x), fx: lerp(a[2], b[2], x), fy: lerp(a[3], b[3], x) };
}

export type FingerKey = { a: number; b: number; x0: number; y0: number; x1: number; y1: number; tap?: boolean };
export const FINGER: FingerKey[] = [
  { a: 8.1, b: 8.8, x0: 195, y0: 808, x1: 195, y1: 808, tap: true },
  { a: 10.8, b: 14.9, x0: 290, y0: 313, x1: 90, y1: 313 },
  { a: 22.9, b: 23.6, x0: 200, y0: 588, x1: 200, y1: 588, tap: true },
  { a: 49.9, b: 50.6, x0: 332, y0: 786, x1: 332, y1: 786, tap: true },
  { a: 57.9, b: 58.9, x0: 195, y0: 70, x1: 195, y1: 420 },
];

/** Caption windows [in, out], in content.captions order. */
export const CAPTIONS: Array<[number, number]> = [
  [2.4, 7.4], [10.6, 16.0], [17.0, 23.4], [25.0, 30.6], [35.6, 43.0], [44.0, 49.4], [51.0, 57.4], [60.2, 68.2],
];

/** Host-talking window (music ducked); the mixer panel and markers.md use it. */
export const HOST_IN = 35.6;
export const HOST_OUT = 43.0;

export type SfxKind = "tick" | "tap" | "chime" | "air" | "key" | "noise";
export type SfxEvent = { t: number; k: SfxKind };

/** Sound event table (EV in the sample). */
export const EV: SfxEvent[] = (() => {
  const ev: SfxEvent[] = [];
  let prev = Math.floor(tuneF(10.9) * 5);
  for (let t = 11; t < 23.2; t += 1 / 120) {
    const v = Math.floor(tuneF(t) * 5);
    if (v !== prev) {
      ev.push({ t, k: "tick" });
      prev = v;
    }
  }
  ([[8.4, "tap"], [23.2, "tap"], [50.2, "tap"], [15.0, "chime"], [22.6, "chime"], [31.0, "chime"]] as const).forEach(([t, k]) => ev.push({ t, k }));
  [9.0, 24.0, 31.0, 50.3, 58.2, 60.4].forEach((t) => ev.push({ t, k: "air" }));
  const n = content.prompt.length;
  for (let i = 1; i <= n; i++) ev.push({ t: TYPE_START + (i / n) * (TYPE_END - TYPE_START), k: "key" });
  ev.push({ t: 24.2, k: "noise" });
  return ev.sort((a, b) => a.t - b.t);
})();
