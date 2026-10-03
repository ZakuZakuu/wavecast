// Pure port of docs/design/frost/Cover2.dc.html (cover v2). Same params =>
// same cover. The seed picks one of the station's three templates, a
// procedural palette around the station hue (dark / light / vivid mode) and
// the template's composition.
import { stationById, type CoverTemplate, type StationId } from "../stations";

export type CoverParams = {
  stationId: StationId;
  /** From the programme id (seedFromId), so every surface draws the same cover. */
  seed: number;
  heading: string;
  /** No text at all (small sizes): graphics only. */
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

export type CoverPalette = { mode: "dark" | "light" | "vivid"; bg: string; p1: string; p2: string; ink: string };

/** Absolute placement in cqw (null = auto). */
export type CoverBox = { left: number | null; right: number | null; top: number | null; bottom: number | null; width: number | null };

export type CoverTitle = CoverBox & {
  serif: boolean;
  size: number;
  weight: number;
  lh: number;
  ls: string;
  align: "left" | "center" | "right";
  vertical: boolean;
  color: string;
  /** Surface behind the title, for contrast checks. */
  on: string;
};

export type CoverStationLine = CoverBox & { align: "left" | "center" | "right"; color: string; freqText: string };

export type CoverNumber = CoverBox & { color: string };

export type BuiltCover = {
  template: CoverTemplate;
  bare: boolean;
  palette: CoverPalette;
  bg: string;
  slots: CoverSlot[];
  /** Big frequency numeral (freq template only); null when hidden. */
  number: CoverNumber | null;
  title: CoverTitle;
  stationLine: CoverStationLine;
  heading: string;
  station: string;
  freq: string;
};

const SLOT_COUNT = 8;
/** WCAG AA for the cover title against the surface it sits on. */
export const MIN_TITLE_CONTRAST = 4.5;
const DARK_TEXT = "#1C1C1E";
const LIGHT_TEXT = "#FAF8F4";

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

export function hsl(h: number, s: number, l: number): string {
  h = ((h % 360) + 360) % 360;
  s /= 100;
  l /= 100;
  const k = (n: number) => (n + h / 30) % 12;
  const a = s * Math.min(l, 1 - l);
  const f = (n: number) => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  const x = (v: number) => Math.round(v * 255).toString(16).padStart(2, "0");
  return "#" + x(f(0)) + x(f(8)) + x(f(4));
}

export function luminance(hex: string): number {
  const h = String(hex || "#000000").replace("#", "");
  const v = [0, 2, 4]
    .map((i) => parseInt(h.substring(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)));
  return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2];
}

export function contrastRatio(a: string, b: string): number {
  const la = luminance(a);
  const lb = luminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

/** The text colour (near-black or warm white) with more contrast on `hex`. */
export function textOn(hex: string): string {
  return contrastRatio(DARK_TEXT, hex) >= contrastRatio(LIGHT_TEXT, hex) ? DARK_TEXT : LIGHT_TEXT;
}

export function isDarkColour(hex: string): boolean {
  return textOn(hex) === LIGHT_TEXT;
}

/**
 * A colour that may carry the title. Mid-luminance colours (roughly 0.15–0.25)
 * reach 4.5:1 with neither text colour, so the lightness is pushed out of
 * that band — darker if it is on the dark side, lighter otherwise. Hue and
 * saturation stay; most seeds need no change.
 */
export function surface(h: number, s: number, l: number): string {
  let hex = hsl(h, s, l);
  if (contrastRatio(textOn(hex), hex) >= MIN_TITLE_CONTRAST) return hex;
  const step = textOn(hex) === LIGHT_TEXT ? -1 : 1;
  for (let next = l + step; next >= 0 && next <= 100; next += step) {
    hex = hsl(h, s, next);
    if (contrastRatio(textOn(hex), hex) >= MIN_TITLE_CONTRAST) return hex;
  }
  return hex;
}

type StationLook = { hue: number; dark: number };

/** Palette per Cover2 `palette()`: hue jitter, then dark / light / vivid by the station's odds. */
export function coverPalette(R: () => number, look: StationLook): CoverPalette {
  const h = look.hue + (R() * 2 - 1) * 16;
  const accent = h + (R() < 0.5 ? 150 : -150) + (R() * 2 - 1) * 20;
  const roll = R();
  if (roll < look.dark) {
    return {
      mode: "dark",
      bg: surface(h, 30 + R() * 15, 11 + R() * 6),
      p1: surface(h, 35 + R() * 18, 34 + R() * 12),
      p2: surface(18 + R() * 22, 72, 74 + R() * 8),
      ink: hsl(h, 30, 88),
    };
  }
  if (roll < look.dark + (1 - look.dark) / 2) {
    return {
      mode: "light",
      bg: surface(h, 36 + R() * 22, 85 + R() * 7),
      p1: surface(h, 45 + R() * 20, 28 + R() * 10),
      p2: surface(accent, 62, 54),
      ink: hsl(h, 40, 15),
    };
  }
  return {
    mode: "vivid",
    bg: surface(h, 45 + R() * 15, 44 + R() * 8),
    p1: surface(h, 40, 86 + R() * 6),
    p2: surface(h, 50, 15 + R() * 6),
    ink: hsl(h, 40, 12),
  };
}

function circ(cx: number, cy: number, r: number): string {
  return "M" + r2(cx - r) + " " + r2(cy) + "a" + r2(r) + " " + r2(r) + " 0 1 0 " + r2(2 * r) + " 0a" + r2(r) + " " + r2(r) + " 0 1 0 " + r2(-2 * r) + " 0Z";
}

function box(x: number, y: number, w: number, h: number): string {
  return "M" + r2(x) + " " + r2(y) + "h" + r2(w) + "v" + r2(h) + "h" + r2(-w) + "Z";
}

/** Visual width: CJK counts 1, everything else 0.56. */
export function visualLength(text: string): number {
  let n = 0;
  for (const ch of text) n += /[㐀-鿿豈-﫿]/.test(ch) ? 1 : 0.56;
  return n;
}

export function longestLine(text: string): number {
  return Math.max(1, ...String(text).split("\n").map(visualLength));
}

const lineCount = (text: string) => String(text).split("\n").length;

type TitleSpec = Partial<CoverBox> & Partial<Omit<CoverTitle, keyof CoverBox | "on">> & { size: number; on: string };
type StationSpec = Partial<CoverBox> & Partial<Omit<CoverStationLine, keyof CoverBox>>;
type TemplateOut = {
  slots: Array<Partial<CoverSlot>>;
  number?: Partial<CoverBox>;
  title: TitleSpec;
  station: StationSpec;
};
type Meta = { heading: string; freq: string };

const TEMPLATES: Record<CoverTemplate, (R: () => number, c: CoverPalette, m: Meta) => TemplateOut> = {
  freq(R, c, m) {
    const flip = R() < 0.5;
    const ty = flip ? 40 + R() * 10 : 52 + R() * 12;
    const step = R() < 0.5 ? 2.2 : 3;
    let ticks = "";
    for (let i = 0, x = 6; x <= 94; x += step, i += 1) ticks += "M" + r2(x) + " " + r2(ty + (i % 5 === 0 ? -3 : 0)) + "V" + r2(ty + 3);
    const fx = 6 + (((parseFloat(m.freq) || 97.4) - 87) / 21) * 88;
    const size = Math.min(15, 80 / longestLine(m.heading));
    const nl = lineCount(m.heading);
    return {
      slots: [
        { d: ticks, stroke: c.p1, sw: 0.45, so: 0.75 },
        { d: "M" + r2(fx) + " " + r2(ty - 7) + "V" + r2(ty + 5), stroke: c.p2, sw: 1.1 },
        { d: circ(fx, ty - 8, 1.5), fill: c.p2 },
      ],
      number: flip ? { right: 3, top: -7 } : { left: 3, bottom: -6 },
      title: flip
        ? { left: 7, bottom: 8, width: 86, size, on: c.bg }
        : { left: 7, top: 7, width: 86, size, on: c.bg },
      station: flip
        ? { left: 7, top: ty + 6, freqText: "" }
        : { left: 7, top: Math.max(ty - 12, 9 + nl * size * 1.15), freqText: "" },
    };
  },
  split(R, c, m) {
    const top = R() < 0.55;
    const split = 50 + R() * 16;
    const size = Math.min(15, 86 / longestLine(m.heading));
    const fy = top ? 0 : 100 - split;
    const cr = 5 + R() * 4;
    const cy = top ? split + 14 + R() * 18 : 12 + R() * (100 - split - 24);
    const n = 2 + Math.floor(R() * 3);
    let rules = "";
    const ry = top ? split + 14 : 17;
    for (let i = 0; i < n; i += 1) rules += box(7, ry + i * 5, 42 - i * 9, 0.35);
    return {
      slots: [
        { d: box(0, fy, 100, split), fill: c.p1 },
        { d: circ(72 + R() * 16, cy, cr), fill: c.p2 },
        { d: rules, fill: textOn(c.bg), o: 0.28 },
      ],
      title: top
        ? { left: 7, right: 7, bottom: 100 - split + 3, size, on: c.p1 }
        : { left: 7, right: 7, top: fy + 5, size, on: c.p1 },
      station: top ? { left: 7, top: split + 5 } : { left: 7, top: 7 },
    };
  },
  horizon(R, c, m) {
    const hy = 54 + R() * 16;
    const right = R() < 0.5;
    const r = 10 + R() * 9;
    const cx = right ? 74 + R() * 12 : 14 + R() * 12;
    const cy = hy + r * 0.15;
    let refl = "";
    const nr = 4 + Math.floor(R() * 4);
    for (let i = 0; i < nr; i += 1) {
      const w = r * 1.7 * (1 - i * (0.7 / nr));
      refl += box(cx - w / 2, hy + 3 + i * (30 / nr), w, Math.max(0.3, 1.1 - i * 0.12));
    }
    let stars = "";
    if (luminance(c.bg) < 0.12 && R() < 0.75) {
      const ns = 16 + Math.floor(R() * 22);
      for (let i = 0; i < ns; i += 1) stars += circ(R() * 100, R() * (hy - 14), 0.25 + R() * 0.35);
    }
    const size = Math.min(14, 56 / longestLine(m.heading));
    return {
      slots: [
        { d: stars, fill: c.ink, o: 0.55 },
        { d: circ(cx, cy, r * 1.9), fill: c.p1, o: 0.2 },
        { d: circ(cx, cy, r * 1.4), fill: c.p1, o: 0.32 },
        { d: circ(cx, cy, r), fill: c.p2 },
        { d: box(0, hy, 100, 100 - hy), fill: c.bg },
        { d: refl, fill: c.p2, o: 0.45 },
        { d: box(0, hy - 0.2, 100, 0.4), fill: c.p1, o: 0.7 },
      ],
      title: right
        ? { left: 7, bottom: 100 - hy + 2.5, width: 60, size, on: c.bg }
        : { right: 7, bottom: 100 - hy + 2.5, width: 60, size, align: "right", on: c.bg },
      station: right ? { left: 7, top: hy + 5 } : { right: 7, top: hy + 5, align: "right" },
    };
  },
  column(R, c, m) {
    const left = R() < 0.5;
    const w = 36 + R() * 6;
    const colX = left ? 0 : 100 - w;
    const x0 = left ? w + 8 : 6;
    const x1 = left ? 94 : 100 - w - 8;
    const nl = lineCount(m.heading);
    const size = Math.min(14.5, 64 / longestLine(m.heading), (w - 8) / (1.3 * nl));
    let pattern = "";
    if (R() < 0.6) {
      const cols = 6;
      const rows = 11;
      const step = (x1 - x0) / (cols - 1);
      const fx = R() * cols;
      const fy = R() * rows;
      for (let i = 0; i < cols; i += 1) {
        for (let j = 0; j < rows; j += 1) {
          const rr = Math.max(0.35, 3.3 - Math.hypot(i - fx, j - fy) * 0.42 + (R() - 0.5) * 0.5);
          pattern += circ(x0 + i * step, 8 + j * 8.4, Math.min(rr, step * 0.48));
        }
      }
    } else {
      for (let y = 8; y < 93; y += 6 + R() * 2) {
        const len = 0.25 + R() * 0.75;
        pattern += box(left ? x0 : x1 - (x1 - x0) * len, y, (x1 - x0) * len, 1.4 + R() * 1.2);
      }
    }
    const textW = nl * size * 1.3;
    return {
      slots: [
        { d: box(colX, 0, w, 100), fill: c.p2 },
        { d: pattern, fill: c.p1, o: 0.9 },
      ],
      title: { left: colX + (w - textW) / 2, top: 8, serif: true, weight: 900, size, lh: 1.25, ls: "0.08em", vertical: true, on: c.p2 },
      station: { left: colX, width: w, bottom: 6, align: "center", color: textOn(c.p2) },
    };
  },
  label(R, c, m) {
    const cx = 44 + R() * 12;
    const cy = 44 + R() * 12;
    const lr = 27 + R() * 6;
    let grooves = "";
    const st = 1.6 + R() * 0.7;
    for (let r = lr + 2; r < 56; r += st) grooves += circ(cx, cy, r);
    let arcs = "";
    const na = 1 + Math.floor(R() * 2);
    for (let i = 0; i < na; i += 1) {
      const ri = lr + 4 + R() * 14;
      const a0 = R() * 6.28;
      const a1 = a0 + 0.6 + R() * 1.2;
      arcs += "M" + r2(cx + ri * Math.cos(a0)) + " " + r2(cy + ri * Math.sin(a0)) + "A" + r2(ri) + " " + r2(ri) + " 0 0 1 " + r2(cx + ri * Math.cos(a1)) + " " + r2(cy + ri * Math.sin(a1));
    }
    const nl = lineCount(m.heading);
    const size = Math.min(10.5, (lr * 1.5) / longestLine(m.heading));
    const th = nl * size * 1.2;
    return {
      slots: [
        { d: grooves, stroke: c.p1, sw: 0.35, so: 0.6 },
        { d: arcs, stroke: c.p1, sw: 1.1 },
        { d: circ(cx, cy, lr), fill: c.p2 },
      ],
      title: { left: cx - lr, width: lr * 2, top: cy - th / 2 - 2, size, serif: true, weight: 900, lh: 1.2, align: "center", on: c.p2 },
      station: { right: 5, bottom: 4, align: "right" },
    };
  },
  contour(R, c, m) {
    const k = Math.floor(R() * 3);
    const cx = [70 + R() * 12, 22 + R() * 14, 82 + R() * 8][k];
    const cy = [70 + R() * 12, 74 + R() * 10, 44 + R() * 18][k];
    const n = 9 + Math.floor(R() * 7);
    const gap = 6.2 + R() * 1.4;
    const amp = 0.08 + R() * 0.08;
    const ph1 = R() * 6.28;
    const ph2 = R() * 6.28;
    const nl = lineCount(m.heading);
    const size = Math.min(13.5, 64 / longestLine(m.heading));
    const zoneY = 7 + nl * size * 1.15 + 9;
    // The title owns the top-left zone; contours break around it.
    const zone = (x: number, y: number) => x < 74 && y < zoneY;
    let rings = "";
    let inner = "";
    for (let j = 1; j <= n; j += 1) {
      const base = j * gap + R();
      let seg = "";
      let on = false;
      for (let q = 0; q <= 80; q += 1) {
        const t = (q / 80) * Math.PI * 2;
        const rr = base * (1 + amp * Math.sin(3 * t + ph1 + j * 0.2) + amp * 0.5 * Math.sin(5 * t + ph2));
        const x = cx + rr * Math.cos(t);
        const y = cy + rr * Math.sin(t);
        if (zone(x, y)) {
          on = false;
          continue;
        }
        seg += (on ? "L" : "M") + r2(x) + " " + r2(y);
        on = true;
      }
      if (j === 1) inner = seg + "Z";
      else rings += seg;
    }
    return {
      slots: [
        { d: rings, stroke: c.p1, sw: 0.5 },
        { d: inner, fill: c.p2 },
      ],
      title: { left: 7, top: 7, width: 66, size, on: c.bg },
      station: { left: 7, top: 7 + nl * size * 1.15 + 2 },
    };
  },
};

function normalizeSlot(slot: Partial<CoverSlot> | null): CoverSlot {
  return {
    d: slot?.d || "M0 0",
    fill: slot?.fill ?? "none",
    o: slot?.o ?? 1,
    stroke: slot?.stroke ?? "none",
    sw: slot?.sw ?? 0,
    so: slot?.so ?? 1,
  };
}

function boxOf(spec: Partial<CoverBox>): CoverBox {
  const v = (n: number | null | undefined) => (n === null || n === undefined ? null : r2(n));
  return { left: v(spec.left), right: v(spec.right), top: v(spec.top), bottom: v(spec.bottom), width: v(spec.width) };
}

/** Seeded stream, template and palette, drawn in Cover2's order. */
export function coverSetup(stationId: StationId, seed: number) {
  const station = stationById(stationId);
  const R = rng(seed * 2654435761 + station.cover.hue * 97 + 13);
  const template = station.templates[Math.floor(R() * station.templates.length)];
  const palette = coverPalette(R, station.cover);
  return { R, template, palette };
}

export function buildCover(params: CoverParams): BuiltCover {
  const station = stationById(params.stationId);
  const seed = Number(params.seed) || 0;
  const heading = params.heading ?? "";
  const freq = station.freq.toFixed(1);
  const { R, template, palette } = coverSetup(station.id, seed);
  const out = TEMPLATES[template](R, palette, { heading, freq });
  const bare = params.bare === true;
  const slots = out.slots.map(normalizeSlot);
  while (slots.length < SLOT_COUNT) slots.push(normalizeSlot(null));
  const t = out.title;
  return {
    template,
    bare,
    palette,
    bg: palette.bg,
    slots,
    number: out.number && !bare ? { ...boxOf(out.number), color: palette.p1 } : null,
    title: {
      ...boxOf(t),
      serif: t.serif ?? false,
      size: r2(t.size),
      weight: t.weight ?? 700,
      lh: t.lh ?? 1.15,
      ls: t.ls ?? "-0.01em",
      align: t.align ?? "left",
      vertical: t.vertical ?? false,
      color: t.color ?? textOn(t.on),
      on: t.on,
    },
    stationLine: {
      ...boxOf(out.station),
      align: out.station.align ?? "left",
      color: out.station.color ?? textOn(palette.bg),
      freqText: out.station.freqText ?? "FM ",
    },
    heading,
    station: station.name,
    freq,
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
