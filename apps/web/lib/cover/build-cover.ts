// Pure port of docs/design/frost/TypeCover.dc.html. Same params => same cover.
import type { CoverPalette, CoverTemplate } from "../stations";

export type CoverParams = {
  template: CoverTemplate;
  seed: number;
  bg: string;
  p1: string;
  p2: string;
  ink: string;
  heading: string;
  station: string;
  freq: string;
  bare?: boolean;
};

export type CoverSlot = {
  d: string;
  fill: string;
  o: number;
  stroke: string;
  sw: number;
  so: number;
};

export type BuiltCover = {
  template: CoverTemplate;
  bare: boolean;
  slots: CoverSlot[];
  titleSize: number;
  bg: string;
  p1: string;
  onBg: string;
  onP1: string;
  onP2: string;
  splitBottom: number;
  splitTop: number;
  heading: string;
  station: string;
  freq: string;
};

const r2 = (n: number) => Math.round(n * 100) / 100;

function rng(seed: number) {
  let a = seed >>> 0;
  return function next() {
    a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function circ(cx: number, cy: number, r: number): string {
  return "M" + r2(cx - r) + " " + r2(cy) + "a" + r2(r) + " " + r2(r) + " 0 1 0 " + r2(2 * r) + " 0a" + r2(r) + " " + r2(r) + " 0 1 0 " + r2(-2 * r) + " 0Z";
}

function box(x: number, y: number, w: number, h: number): string {
  return "M" + r2(x) + " " + r2(y) + "h" + r2(w) + "v" + r2(h) + "h" + r2(-w) + "Z";
}

function luminance(hex: string): number {
  const h = String(hex || "#000000").replace("#", "");
  const v = [0, 2, 4]
    .map((i) => parseInt(h.substring(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)));
  return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2];
}

export function textOn(hex: string): string {
  return luminance(hex) > 0.34 ? "#1C1C1E" : "#FAF8F4";
}

export function isDarkColour(hex: string): boolean {
  return luminance(hex) <= 0.34;
}

/** Visual width: CJK counts 1, everything else 0.56. */
export function visualLength(text: string): number {
  let n = 0;
  for (const ch of text) n += /[㐀-鿿豈-﫿]/.test(ch) ? 1 : 0.56;
  return n;
}

export function longestLine(text: string): number {
  return Math.max(1, ...String(text).split("\n").map(visualLength));
}

type Partial6 = Partial<CoverSlot>;
type TemplateOut = { slots: Partial6[]; size: number; split?: number };
type Meta = { heading: string; freq: string };

const TEMPLATES: Record<CoverTemplate, (R: () => number, c: CoverPalette, m: Meta) => TemplateOut> = {
  freq(_R, c, m) {
    let ticks = "";
    for (let i = 0; i <= 40; i += 1) {
      const x = 6 + i * 2.2;
      ticks += "M" + r2(x) + " " + (i % 5 === 0 ? 55.5 : 58.5) + "V61";
    }
    const f = parseFloat(m.freq) || 97.4;
    const fx = 6 + ((f - 87) / 21) * 88;
    return {
      slots: [
        { d: ticks, stroke: c.p1, sw: 0.45, so: 0.75 },
        { d: "M" + r2(fx) + " 51.5V63", stroke: c.p2, sw: 1.1 },
        { d: circ(fx, 50.5, 1.5), fill: c.p2 },
      ],
      size: Math.min(15, 80 / longestLine(m.heading)),
    };
  },
  label(R, c, m) {
    let grooves = "";
    for (let r = 33; r < 49; r += 1.7 + R() * 0.5) grooves += circ(50, 50, r);
    const ri = 36 + R() * 11;
    const a0 = R() * 6.28;
    const a1 = a0 + 0.7 + R() * 1.2;
    const arc = "M" + r2(50 + ri * Math.cos(a0)) + " " + r2(50 + ri * Math.sin(a0)) + "A" + r2(ri) + " " + r2(ri) + " 0 0 1 " + r2(50 + ri * Math.cos(a1)) + " " + r2(50 + ri * Math.sin(a1));
    return {
      slots: [
        { d: grooves, stroke: c.p1, sw: 0.35, so: 0.6 },
        { d: arc, stroke: c.p1, sw: 1.1 },
        { d: circ(50, 50, 31), fill: c.p2 },
      ],
      size: Math.min(10.5, 46 / longestLine(m.heading)),
    };
  },
  horizon(R, c, m) {
    const hy = 64;
    const r = 12 + R() * 4;
    const cx = 80 + R() * 6;
    const cy = hy + r * 0.18;
    let refl = "";
    for (let i = 0; i < 6; i += 1) {
      const y = hy + 3.2 + i * 4.2;
      const w = r * 1.6 * (1 - i * 0.14);
      refl += box(cx - w / 2, y, w, 1.1 - i * 0.12);
    }
    return {
      slots: [
        { d: circ(cx, cy, r * 1.9), fill: c.p1, o: 0.18 },
        { d: circ(cx, cy, r * 1.4), fill: c.p1, o: 0.3 },
        { d: circ(cx, cy, r), fill: c.p2 },
        { d: box(0, hy, 100, 36), fill: c.bg },
        { d: refl, fill: c.p2, o: 0.45 },
        { d: box(0, hy - 0.2, 100, 0.4), fill: c.p1, o: 0.7 },
      ],
      size: Math.min(14, 58 / longestLine(m.heading)),
    };
  },
  column(R, c, m) {
    let dots = "";
    let big = "";
    const cols = 6;
    const rows = 11;
    const x0 = 48;
    const y0 = 7;
    const step = 8.4;
    const fx = R() * cols;
    const fy = R() * rows;
    for (let i = 0; i < cols; i += 1) {
      for (let j = 0; j < rows; j += 1) {
        const d = Math.hypot(i - fx, j - fy);
        const rr = Math.max(0.35, 3.4 - d * 0.42 + (R() - 0.5) * 0.5);
        if (rr > 3) big += circ(x0 + i * step, y0 + j * step + 1, rr);
        else dots += circ(x0 + i * step, y0 + j * step + 1, rr);
      }
    }
    return {
      slots: [
        { d: box(0, 0, 40, 100), fill: c.p2 },
        { d: dots, fill: c.p1 },
        { d: big, fill: c.p1, o: 0.85 },
      ],
      size: Math.min(14.5, 64 / longestLine(m.heading)),
    };
  },
  contour(R, c, m) {
    const cx = 68 + R() * 10;
    const cy = 70 + R() * 10;
    const ph1 = R() * 6.28;
    const ph2 = R() * 6.28;
    // The title owns the top-left zone; contours break around it.
    const zone = (x: number, y: number) => x < 74 && y < 46;
    let lines = "";
    let inner = "";
    for (let j = 1; j <= 13; j += 1) {
      const base = j * 6.8 + R();
      let seg = "";
      let drawing = false;
      for (let k = 0; k <= 80; k += 1) {
        const t = (k / 80) * Math.PI * 2;
        const rr = base * (1 + 0.12 * Math.sin(3 * t + ph1 + j * 0.2) + 0.06 * Math.sin(5 * t + ph2));
        const x = cx + rr * Math.cos(t);
        const y = cy + rr * Math.sin(t);
        if (zone(x, y)) {
          drawing = false;
          continue;
        }
        seg += (drawing ? "L" : "M") + r2(x) + " " + r2(y);
        drawing = true;
      }
      if (j === 1) inner = seg + "Z";
      else lines += seg;
    }
    return {
      slots: [
        { d: lines, stroke: c.p1, sw: 0.5 },
        { d: inner, fill: c.p2 },
      ],
      size: Math.min(13.5, 64 / longestLine(m.heading)),
    };
  },
  split(R, c, m) {
    const split = 58 + R() * 8;
    let rules = "";
    for (let i = 0; i < 3; i += 1) rules += box(7, split + 16 + i * 5.5, 40 - i * 9, 0.35);
    return {
      slots: [
        { d: box(0, 0, 100, split), fill: c.p1 },
        { d: circ(80 + R() * 6, split + 18 + R() * 8, 5 + R() * 3), fill: c.p2 },
        { d: rules, fill: c.ink, o: 0.3 },
      ],
      size: Math.min(15, 86 / longestLine(m.heading)),
      split,
    };
  },
};

function normalizeSlot(slot: Partial6 | null): CoverSlot {
  return {
    d: slot?.d || "M0 0",
    fill: slot?.fill ?? "none",
    o: slot?.o ?? 1,
    stroke: slot?.stroke ?? "none",
    sw: slot?.sw ?? 0,
    so: slot?.so ?? 1,
  };
}

export function buildCover(params: CoverParams): BuiltCover {
  const template: CoverTemplate = TEMPLATES[params.template] ? params.template : "column";
  const seed = Number(params.seed) || 0;
  const palette: CoverPalette = { bg: params.bg, p1: params.p1, p2: params.p2, ink: params.ink };
  const R = rng(seed * 7919 + template.length * 131 + 29);
  const out = TEMPLATES[template](R, palette, { heading: params.heading, freq: params.freq });
  const slots = out.slots.map(normalizeSlot);
  while (slots.length < 6) slots.push(normalizeSlot(null));
  const split = out.split ?? 60;
  return {
    template,
    bare: params.bare === true,
    slots,
    titleSize: r2(out.size),
    bg: palette.bg,
    p1: palette.p1,
    onBg: textOn(palette.bg),
    onP1: textOn(palette.p1),
    onP2: textOn(palette.p2),
    splitBottom: r2(100 - split + 3),
    splitTop: r2(split + 5),
    heading: params.heading,
    station: params.station,
    freq: params.freq,
  };
}

/** Standalone SVG (no title text) — used for canvas export (MediaSession artwork). */
export function bareCoverSvg(params: CoverParams, size = 512): string {
  const cover = buildCover({ ...params, bare: true });
  const paths = cover.slots.map((slot) => (
    `<path d="${slot.d}" fill="${slot.fill}" fill-opacity="${slot.o}" stroke="${slot.stroke}" stroke-width="${slot.sw}" stroke-opacity="${slot.so}" stroke-linecap="round" stroke-linejoin="round"/>`
  )).join("");
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice"><rect width="100" height="100" fill="${cover.bg}"/>${paths}</svg>`;
}
