// Path builders on a 100 x 100 box, shared by the motifs and the styles.
import { r2 } from "./color";
import type { Rng } from "./types";

type Point = readonly [number, number];

export const circle = (cx: number, cy: number, r: number) =>
  `M${r2(cx - r)} ${r2(cy)}a${r2(r)} ${r2(r)} 0 1 0 ${r2(2 * r)} 0a${r2(r)} ${r2(r)} 0 1 0 ${r2(-2 * r)} 0Z`;

export const rect = (x: number, y: number, w: number, h: number) => `M${r2(x)} ${r2(y)}h${r2(w)}v${r2(h)}h${r2(-w)}Z`;

export const rrect = (x: number, y: number, w: number, h: number, r: number) =>
  `M${r2(x + r)} ${r2(y)}H${r2(x + w - r)}A${r} ${r} 0 0 1 ${r2(x + w)} ${r2(y + r)}V${r2(y + h - r)}A${r} ${r} 0 0 1 ${r2(x + w - r)} ${r2(y + h)}H${r2(x + r)}A${r} ${r} 0 0 1 ${r2(x)} ${r2(y + h - r)}V${r2(y + r)}A${r} ${r} 0 0 1 ${r2(x + r)} ${r2(y)}Z`;

export const polygon = (points: Point[]) => "M" + points.map(([x, y]) => `${r2(x)} ${r2(y)}`).join("L") + "Z";

/** A band of sea or hills across the box, filled down to the bottom edge. */
export function wave(y: number, amplitude: number, wavelength: number, phase: number): string {
  let d = `M-5 ${r2(y + amplitude * Math.sin(phase))}`;
  for (let x = -5; x <= 105; x += 2.5) d += `L${x} ${r2(y + amplitude * Math.sin((x / wavelength) * Math.PI * 2 + phase))}`;
  return d + "L105 106L-5 106Z";
}

/** A crescent: the circle (cx, cy, r1) minus a second circle offset by (ox, oy). */
export function crescent(cx: number, cy: number, r1: number, ox: number, oy: number, r2c: number): string {
  const d = Math.hypot(ox, oy);
  const a = (r1 * r1 - r2c * r2c + d * d) / (2 * d);
  const h = Math.sqrt(Math.max(0, r1 * r1 - a * a));
  const mx = cx + (a * ox) / d;
  const my = cy + (a * oy) / d;
  const p1 = [mx + (h * oy) / d, my - (h * ox) / d];
  const p2 = [mx - (h * oy) / d, my + (h * ox) / d];
  return `M${r2(p1[0])} ${r2(p1[1])}A${r1} ${r1} 0 1 0 ${r2(p2[0])} ${r2(p2[1])}A${r2c} ${r2c} 0 0 1 ${r2(p1[0])} ${r2(p1[1])}Z`;
}

/** A leaf from (x, y) pointing along `angle`. */
export function leaf(x: number, y: number, length: number, width: number, angle: number): string {
  const c = Math.cos(angle);
  const s = Math.sin(angle);
  const at = (u: number, v: number): Point => [x + u * c - v * s, y + u * s + v * c];
  const [a, b, d] = [at(length * 0.5, -width), at(length, 0), at(length * 0.5, width)];
  return `M${r2(x)} ${r2(y)}Q${r2(a[0])} ${r2(a[1])} ${r2(b[0])} ${r2(b[1])}Q${r2(d[0])} ${r2(d[1])} ${r2(x)} ${r2(y)}Z`;
}

/** A wobbly closed contour line around (cx, cy). */
export function blob(cx: number, cy: number, radius: number, random: Rng): string {
  const phase = [random() * 6, random() * 6, random() * 6];
  let d = "";
  for (let i = 0; i <= 48; i += 1) {
    const a = (i / 48) * Math.PI * 2;
    const k = 1 + 0.16 * Math.sin(a * 2 + phase[0]) + 0.1 * Math.sin(a * 3 + phase[1]) + 0.06 * Math.sin(a * 5 + phase[2]);
    d += `${i ? "L" : "M"}${r2(cx + radius * k * Math.cos(a))} ${r2(cy + radius * k * Math.sin(a) * 0.85)}`;
  }
  return d + "Z";
}
