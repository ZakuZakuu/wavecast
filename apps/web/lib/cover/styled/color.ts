export { hsl } from "../build-cover";

const channels = (hex: string) => [0, 2, 4].map((i) => parseInt(hex.slice(1 + i, 3 + i), 16));

export function mix(a: string, b: string, t: number): string {
  const x = channels(a);
  const y = channels(b);
  return "#" + x.map((v, i) => Math.round(v + (y[i] - v) * t).toString(16).padStart(2, "0")).join("");
}

export function rgba(hex: string, alpha: number): string {
  const [r, g, b] = channels(hex);
  return `rgba(${r},${g},${b},${alpha})`;
}

export const clamp = (value: number, low: number, high: number) => Math.max(low, Math.min(high, value));
export const r2 = (n: number) => Math.round(n * 100) / 100;

/** FNV-1a over code points: seeds a cover's random stream from its style, station, motif and heading. */
export function hashString(text: string): number {
  let h = 2166136261;
  for (const ch of text) h = Math.imul(h ^ ch.codePointAt(0)!, 16777619);
  return h >>> 0;
}
