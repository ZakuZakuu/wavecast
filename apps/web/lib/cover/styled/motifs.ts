// The twenty pictures. Each is drawn once, on a 100 x 100 box, as roles (primary, secondary by depth,
// detail, accent, cut = see-through, lit = lights); every style colours the roles its own way.
import { r2 } from "./color";
import { blob, circle, crescent, leaf, polygon, rect, rrect, wave } from "./shapes";
import type { CoverMotif, Motif, Rng } from "./types";

const ring = (cx: number, cy: number, radii: number[]) => radii.map((r) => circle(cx, cy, r)).join("");
/** Points of a radial tick/ray pattern over the upper half of a disc centred at (50, cy). */
function radial(cy: number, count: number, inner: number, outer: (i: number) => number): string {
  let d = "";
  for (let i = 0; i <= count; i += 1) {
    const a = Math.PI + (i / count) * Math.PI;
    d += `M${r2(50 + inner * Math.cos(a))} ${r2(cy + inner * Math.sin(a))}L${r2(50 + outer(i) * Math.cos(a))} ${r2(cy + outer(i) * Math.sin(a))}`;
  }
  return d;
}

/** A close-up of a dreadnought at real proportions: neck at the top, shoulders, rosette hole, waist, bridge. */
function strings(): Motif {
  const K = 1.8;
  const T = (x: number, y: number): [number, number] => [50 + K * (x - 50), 50 + K * (y - 54)];
  const at = (command: string, ...points: Array<[number, number]>) => command + points.map(([x, y]) => T(x, y).map(r2).join(" ")).join(" ");
  const quad = (points: Array<[number, number]>) => polygon(points.map(([x, y]) => T(x, y)));
  const hole = (x: number, y: number, r: number) => { const [cx, cy] = T(x, y); return circle(cx, cy, r2(r * K)); };
  const body = at("M", [47.4, 42]) + at("C", [47.4, 46], [35.5, 44], [35.5, 54]) + at("C", [35.5, 61], [38.5, 62], [38.5, 67]) + at("C", [38.5, 73], [30.5, 74], [30.5, 85])
    + at("C", [30.5, 105], [69.5, 105], [69.5, 85]) + at("C", [69.5, 74], [61.5, 73], [61.5, 67]) + at("C", [61.5, 62], [64.5, 61], [64.5, 54]) + at("C", [64.5, 44], [52.6, 46], [52.6, 42]) + "Z";
  const frets = [26.6, 30.6, 34.4, 38].map((y) => at("M", [47.6, y]) + at("L", [52.4, y])).join("");
  const wires = Array.from({ length: 6 }, (_, i) => at("M", [48.15 + i * 0.74, 20]) + at("L", [48.15 + i * 0.74, 79])).join("");
  return { focus: [50, 59], fr: 16, noZoom: true, view: [50, 54], items: [
    { role: "primary", mode: "fill", d: body },
    { role: "secondary", mode: "fill", z: 0, d: quad([[47.6, 12], [52.4, 12], [52.6, 46], [47.4, 46]]) },
    { role: "secondary", mode: "fill", z: 1, d: hole(50, 59, 5.6) + hole(50, 59, 4.7) + quad([[45, 78], [55, 78], [55, 80.4], [45, 80.4]]) },
    { role: "cut", mode: "fill", d: hole(50, 59, 4.2) },
    { role: "detail", mode: "stroke", sw: 0.8, d: frets },
    { role: "detail", mode: "stroke", sw: 0.4, d: wires },
    { role: "accent", mode: "fill", d: hole(50, 36.2, 0.7) + hole(50, 28.6, 0.7) },
  ] };
}

export const MOTIFS: Record<CoverMotif, (random: Rng) => Motif> = {
  rain(random) {
    let streaks = "";
    for (let i = 0; i < 18; i += 1) { const x = random() * 100; const y = random() * 70; const len = 10 + random() * 16; streaks += `M${r2(x)} ${r2(y)}l${r2(-len * 0.2)} ${r2(len)}`; }
    return { focus: [66, 58], view: [60, 58], items: [
      { role: "primary", mode: "fill", d: circle(66, 58, 17) + circle(36, 70, 9) + circle(88, 76, 7) },
      { role: "detail", mode: "stroke", sw: 0.45, d: streaks },
      { role: "secondary", mode: "fill", z: 0, d: rect(-3, 86, 106, 20) },
      { role: "accent", mode: "fill", d: circle(24, 92, 2.3) + circle(31, 92.4, 2.3) },
    ] };
  },
  vinyl: () => ({ focus: [54, 50], view: [54, 50], items: [
    { role: "primary", mode: "fill", d: circle(54, 50, 36) },
    { role: "detail", mode: "stroke", sw: 0.35, d: ring(54, 50, [14, 18, 22, 26, 30, 33.5]) + "M96 8L68 42" },
    { role: "secondary", mode: "fill", z: 0, d: circle(54, 50, 11) },
    { role: "accent", mode: "fill", d: circle(54, 50, 2) },
  ] }),
  keys() {
    let white = ""; let black = ""; let staff = "";
    for (let i = 0; i < 8; i += 1) white += rect(7 + i * 11.4, 46, 10.4, 52);
    [0, 1, 3, 4, 5].forEach((i) => { black += rect(7 + i * 11.4 + 7.6, 46, 6.4, 31); });
    [12, 16, 20, 24, 28].forEach((y) => { staff += `M6 ${y}H54`; });
    return { focus: [74, 26], view: [52, 52], items: [
      { role: "primary", mode: "fill", d: circle(74, 26, 19) },
      { role: "secondary", mode: "fill", z: 0, tone: "light", d: white },
      { role: "detail", mode: "stroke", sw: 0.35, d: staff },
      { role: "accent", mode: "fill", tone: "dark", d: black },
    ] };
  },
  skyline(random) {
    let towers = ""; let stripes = "";
    for (let x = -2; x < 102;) { const w = 5 + random() * 6; const h = 12 + random() * 26; towers += rect(x, 100 - h, w, h); x += w + random() * 1.5; }
    for (let i = 0; i < 6; i += 1) stripes += rect(20, 56 + i * 4.8, 60, 1 + i * 0.55);
    return { focus: [50, 52], view: [50, 58], items: [
      { role: "primary", mode: "fill", d: circle(50, 52, 26) },
      { role: "cut", mode: "fill", d: stripes },
      { role: "secondary", mode: "fill", z: 0, d: towers },
    ] };
  },
  moon(random) {
    let stars = "";
    for (let i = 0; i < 40; i += 1) { const x = random() * 100; const y = random() * 62; const r = 0.4 + random() * 0.7; if (Math.hypot(x - 44, y - 38) > 26) stars += circle(x, y, r); }
    return { focus: [44, 38], fr: 20, view: [47, 46], solid: true, items: [
      { role: "primary", mode: "fill", d: crescent(44, 38, 21, 8, -4, 18) },
      { role: "detail", mode: "fill", d: stars },
      { role: "secondary", mode: "fill", z: 0, d: wave(76, 5, 60, random() * 6) },
      { role: "secondary", mode: "fill", z: 1, d: wave(88, 4, 46, random() * 6) },
    ] };
  },
  sea: (random) => ({ focus: [66, 34], view: [58, 52], items: [
    { role: "primary", mode: "fill", d: circle(66, 34, 15) },
    { role: "detail", mode: "stroke", sw: 0.6, d: "M58 56h14M60 60h10M63 64h5" },
    { role: "secondary", mode: "fill", z: 0, d: wave(54, 2.6, 38, random() * 6) },
    { role: "secondary", mode: "fill", z: 1, d: wave(64, 3.2, 30, random() * 6) },
    { role: "secondary", mode: "fill", z: 2, d: wave(75, 3.8, 26, random() * 6) },
    { role: "secondary", mode: "fill", z: 3, d: wave(88, 4, 34, random() * 6) },
    { role: "accent", mode: "fill", d: circle(84, 20, 1.1) + circle(30, 28, 0.8) },
  ] }),
  cassette: () => ({ focus: [50, 50], view: [50, 50], items: [
    { role: "primary", mode: "fill", d: rrect(10, 26, 80, 50, 5) },
    { role: "secondary", mode: "fill", z: 0, d: polygon([[24, 76], [30, 62], [70, 62], [76, 76]]) },
    { role: "cut", mode: "fill", d: rrect(26, 34, 48, 20, 10) },
    { role: "accent", mode: "fill", d: circle(38, 44, 6.5) + circle(62, 44, 6.5) },
    { role: "detail", mode: "stroke", sw: 0.5, d: "M16 30h12M72 30h12M38 44h24" },
  ] }),
  headphones: () => ({ focus: [50, 46], view: [50, 52], items: [
    { role: "primary", mode: "fill", d: "M14 58A36 38 0 0 1 86 58H79.5A29.5 31 0 0 0 20.5 58Z" },
    { role: "secondary", mode: "fill", z: 0, d: rrect(10, 54, 19, 32, 8) + rrect(71, 54, 19, 32, 8) },
    { role: "accent", mode: "fill", d: circle(19.5, 70, 4) + circle(80.5, 70, 4) },
    { role: "detail", mode: "stroke", sw: 0.45, d: "M30 62h40M30 70h40M30 78h40" },
  ] }),
  mic() {
    // A ball grille: a mesh of thin bars, each clipped to the circle.
    let mesh = "";
    for (let k = -3; k <= 3; k += 1) {
      const off = k * 4.4;
      const half = Math.sqrt(Math.max(0, 15.5 * 15.5 - off * off));
      mesh += rect(50 - half, 30 + off - 0.5, 2 * half, 1) + rect(50 + off - 0.5, 30 - half, 1, 2 * half);
    }
    return { focus: [50, 30], fr: 21, view: [50, 46], items: [
      { role: "primary", mode: "fill", d: circle(50, 30, 19) },
      { role: "cut", mode: "fill", d: mesh },
      { role: "secondary", mode: "fill", z: 0, d: rrect(33, 46, 34, 7, 3.5) + polygon([[39, 54], [61, 54], [56, 92], [44, 92]]) + rrect(42, 90, 16, 5, 2.5) },
      { role: "detail", mode: "stroke", sw: 0.7, d: "M82 18A22 22 0 0 1 82 42M88 12A30 30 0 0 1 88 48M18 18A22 22 0 0 0 18 42M12 12A30 30 0 0 0 12 48" },
      { role: "accent", mode: "fill", d: rrect(45.5, 62, 9, 3.6, 1.8) },
    ] };
  },
  tuner: () => ({ focus: [50, 56], view: [50, 60], items: [
    { role: "primary", mode: "fill", d: "M10 72A40 40 0 0 1 90 72Z" },
    { role: "detail", mode: "stroke", sw: 0.55, d: radial(72, 18, 30, (i) => (i % 3 === 0 ? 38 : 34)) },
    { role: "accent", mode: "fill", d: polygon([[49, 72], [51, 72], [66.5, 38]]) + circle(50, 72, 3) },
    { role: "secondary", mode: "fill", z: 0, d: rrect(4, 72, 92, 24, 4) },
    { role: "cut", mode: "fill", d: circle(24, 84, 5) + circle(76, 84, 5) },
  ] }),
  bars(random) {
    let bars = ""; let caps = "";
    for (let i = 0; i < 12; i += 1) { const h = 16 + random() * 56; const x = 8 + i * 7.4; bars += rrect(x, 92 - h, 5.2, h, 2.6); if (h > 52) caps += circle(x + 2.6, 92 - h - 5, 1.6); }
    return { focus: [50, 50], view: [50, 56], items: [
      { role: "primary", mode: "fill", d: bars },
      { role: "accent", mode: "fill", d: caps },
      { role: "detail", mode: "stroke", sw: 0.5, d: "M4 96H96" },
    ] };
  },
  road() {
    const dashes = ([[50, 58, 1], [50, 66, 1.8], [50, 77, 2.8], [50, 91, 4]] as const)
      .map(([x, y, s]) => polygon([[x - s * 0.6, y], [x + s * 0.6, y], [x + s, y + s * 3.2], [x - s, y + s * 3.2]])).join("");
    return { focus: [50, 46], view: [50, 60], items: [
      { role: "primary", mode: "fill", d: circle(50, 48, 15) },
      { role: "secondary", mode: "fill", z: 0, d: rect(-3, 56, 106, 50) },
      { role: "secondary", mode: "fill", z: 1, d: polygon([[47, 56], [53, 56], [96, 102], [4, 102]]) },
      { role: "lit", mode: "fill", d: dashes },
    ] };
  },
  mountains: () => ({ focus: [70, 28], view: [52, 56], items: [
    { role: "primary", mode: "fill", d: circle(70, 28, 12) },
    { role: "secondary", mode: "fill", z: 0, d: polygon([[-5, 70], [18, 42], [34, 60], [52, 36], [76, 66], [92, 50], [105, 66], [105, 106], [-5, 106]]) },
    { role: "secondary", mode: "fill", z: 1, d: polygon([[-5, 84], [24, 58], [44, 80], [66, 56], [88, 78], [105, 68], [105, 106], [-5, 106]]) },
    { role: "secondary", mode: "fill", z: 2, d: polygon([[-5, 96], [30, 82], [60, 94], [105, 84], [105, 106], [-5, 106]]) },
    { role: "accent", mode: "fill", d: circle(22, 20, 1) + circle(38, 12, 0.8) + circle(50, 22, 0.9) },
  ] }),
  forest(random) {
    const trees = (n: number, base: number, low: number, high: number) => {
      let d = "";
      for (let i = 0; i < n; i += 1) {
        const x = (i + 0.5) * (100 / n) + (random() - 0.5) * 4;
        const h = low + random() * (high - low);
        d += polygon([[x - h / 4, base], [x, base - h], [x + h / 4, base]]) + rect(x - 0.9, base, 1.8, 4);
      }
      return d;
    };
    return { focus: [32, 28], view: [50, 56], items: [
      { role: "primary", mode: "fill", d: circle(32, 28, 13) },
      { role: "secondary", mode: "fill", z: 0, d: trees(9, 70, 22, 36) },
      { role: "secondary", mode: "fill", z: 1, d: trees(6, 90, 30, 50) },
      { role: "secondary", mode: "fill", z: 2, d: rect(-3, 94, 106, 12) },
    ] };
  },
  rays: () => ({ focus: [50, 62], view: [50, 60], items: [
    { role: "primary", mode: "fill", d: "M24 70A26 26 0 0 1 76 70Z" },
    { role: "detail", mode: "stroke", sw: 0.9, d: radial(70, 14, 28, (i) => 44 + (i % 2) * 6) },
    { role: "secondary", mode: "fill", z: 0, d: wave(72, 3, 70, 1.2) },
    { role: "secondary", mode: "fill", z: 1, d: wave(86, 3.4, 56, 3.1) },
  ] }),
  windows(random) {
    const blocks = [[4, 40, 24], [30, 22, 30], [62, 48, 18], [82, 34, 20]] as const;
    let panes = "";
    blocks.forEach(([x, top, w]) => {
      for (let y = top + 6; y < 92; y += 7) for (let px = x + 3; px < x + w - 3; px += 5.2) if (random() < 0.62) panes += rect(px, y, 2.6, 3.4);
    });
    return { focus: [76, 16], view: [50, 54], items: [
      { role: "primary", mode: "fill", d: circle(76, 16, 8) },
      { role: "secondary", mode: "fill", z: 0, d: blocks.map(([x, top, w]) => rect(x, top, w, 110 - top)).join("") },
      { role: "lit", mode: "fill", d: panes },
      { role: "detail", mode: "fill", d: circle(18, 12, 0.6) + circle(46, 8, 0.7) + circle(60, 18, 0.5) + circle(30, 20, 0.6) },
    ] };
  },
  ripples: () => ({ focus: [50, 54], fr: 40, view: [50, 54], items: [
    { role: "primary", mode: "fill", d: circle(50, 54, 7) },
    { role: "primary", mode: "stroke", sw: 2.2, d: circle(50, 54, 16) },
    { role: "detail", mode: "stroke", sw: 0.6, d: ring(50, 54, [25, 34, 43]) },
    { role: "accent", mode: "fill", d: circle(76, 28, 1.6) + circle(24, 76, 1.2) + circle(80, 80, 0.9) },
  ] }),
  strings,
  contour(random) {
    const lines = [12, 20, 28, 36, 44].map((r) => blob(54, 48, r, random)).join("");
    return { focus: [54, 48], view: [54, 48], items: [
      { role: "primary", mode: "fill", d: blob(54, 48, 7, random) },
      { role: "detail", mode: "stroke", sw: 0.55, d: lines },
      { role: "accent", mode: "fill", d: circle(54, 48, 2.2) },
    ] };
  },
  plant() {
    let leaves = "";
    for (let i = 0; i < 6; i += 1) { const y = 66 - i * 9.2; const len = 22 - i * 1.6; const w = 5.4 - i * 0.35; leaves += leaf(50, y, len, w, -0.55) + leaf(50, y - 4.6, len, w, Math.PI + 0.55); }
    leaves += leaf(50, 14, 14, 4, -Math.PI / 2);
    return { focus: [50, 38], view: [50, 52], items: [
      { role: "primary", mode: "fill", d: leaves },
      { role: "detail", mode: "stroke", sw: 0.9, d: "M50 70V14" },
      { role: "secondary", mode: "fill", z: 0, d: polygon([[34, 72], [66, 72], [60, 94], [40, 94]]) + rrect(32, 68, 36, 6, 2) },
      { role: "accent", mode: "fill", d: circle(76, 22, 1.4) + circle(24, 30, 1) },
    ] };
  },
};
