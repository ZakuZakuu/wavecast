// Glow: soft colour blobs, the picture as frosted glass, the title on a scrim, a panel or a sheet.
import { FULL, layer, placeMotif, plain, shape } from "../art";
import { clamp, hsl, mix, rgba } from "../color";
import { hues } from "../hues";
import { isLatin, splitTitle, titleBox, type TitleSpec } from "../text";
import { MONO, SANS, view, type StyleFn } from "./kit";

type PillKey = "tl" | "tr" | "bl" | "br" | "tc";
type Box = { x: number; y: number; w: number; h: number };
const PILLS: Record<PillKey, { css: string; r: Box }> = {
  tl: { css: "left:6cqw;top:6cqw;", r: { x: 6, y: 6, w: 36, h: 9 } },
  tr: { css: "right:6cqw;top:6cqw;", r: { x: 58, y: 6, w: 36, h: 9 } },
  bl: { css: "left:6cqw;bottom:6cqw;", r: { x: 6, y: 85, w: 36, h: 9 } },
  br: { css: "right:6cqw;bottom:6cqw;", r: { x: 58, y: 85, w: 36, h: 9 } },
  tc: { css: "left:50%;top:6cqw;transform:translateX(-50%);white-space:nowrap;", r: { x: 30, y: 6, w: 40, h: 9 } },
};
const hitsCircle = (c: { x: number; y: number; r: number }, r: Box) => Math.hypot(c.x - clamp(c.x, r.x, r.x + r.w), c.y - clamp(c.y, r.y, r.y + r.h)) < c.r;
const hitsBox = (a: Box, b: Box) => a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;

type GlowLayout = {
  zoom: number;
  target: [number, number] | null;
  crop?: boolean;
  scrim?: "bottom" | "top" | "left" | "center";
  /** Frosted sheet from this y (cqw) to the bottom. */
  sheet?: number;
  title: TitleSpec;
  pill: PillKey;
};
export const GLOW_LAYOUTS: GlowLayout[] = [
  { zoom: 1, target: null, scrim: "bottom", title: { x: 6, y: 58, w: 70, h: 36, align: "left", anchor: "bottom", max: 15 }, pill: "tl" },
  { zoom: 1.18, target: [50, 40], scrim: "bottom", title: { x: 8, y: 66, w: 84, h: 26, align: "center", anchor: "bottom", max: 14 }, pill: "tc" },
  { zoom: 1.8, target: [70, 72], crop: true, scrim: "top", title: { x: 6, y: 8, w: 80, h: 34, align: "left", anchor: "top", max: 17 }, pill: "bl" },
  { zoom: 1.12, target: [50, 30], sheet: 62, title: { x: 7, y: 65, w: 86, h: 29, align: "left", anchor: "center", max: 14 }, pill: "tl" },
  { zoom: 1.3, target: [64, 50], scrim: "left", title: { x: 7, y: 9, w: 20, h: 82, vertical: true, max: 17, align: "left", anchor: "top" }, pill: "tr" },
];

export const glow: StyleFn = (motif, random, ctx) => {
  const { h, ha } = hues(ctx.station.hue, random);
  const dark = random() < 0.72;
  const bg1 = dark ? hsl(h, 45, 8 + random() * 5) : hsl(h, 40, 90);
  const bg2 = dark ? hsl(h + 20, 52, 20 + random() * 6) : hsl(ha, 50, 82);
  const b1 = hsl(h, 88, dark ? 52 : 62);
  const b2 = hsl(ha, 92, dark ? 58 : 70);
  const b3 = hsl(h + 45, 80, 52);
  const layout = GLOW_LAYOUTS[ctx.layout];
  const blob = (x: number, y: number, color: string, size: number, opacity: number) =>
    plain(`left:${x - size / 2}%;top:${y - size / 2}%;width:${size}%;height:${size}%;background:radial-gradient(circle at 50% 50%,${color} 0%,transparent 62%);opacity:${opacity};`);
  const layers = [
    blob(random() * 70, 55 + random() * 40, b1, 130, 0.9),
    blob(40 + random() * 60, random() * 50, b2, 110, 0.85),
    blob(random() * 100, random() * 100, b3, 80, 0.55),
  ];
  const flip = random() < 0.5;
  const p = placeMotif(motif, FULL, {
    zoom: ctx.bare ? 1 : layout.zoom,
    target: ctx.bare ? null : layout.target,
    flip,
    crop: layout.crop,
    safeTop: ctx.bare || layout.crop || layout.pill.startsWith("b") ? null : 16,
  });
  const white = dark ? "#FFFFFF" : "#1A1530";
  const shadow = dark ? "#06040F" : "#1A1530";
  for (const item of motif.items) {
    if (item.role === "primary") {
      layers.push(shape(item, rgba(b2, 0.9), "filter:blur(3.4cqw);opacity:.8;", p.t));
      if (motif.solid && item.mode !== "stroke") layers.push(layer({ d: item.d, fill: dark ? mix("#FFFFFF", b2, 0.22) : mix(b2, "#FFFFFF", 0.25), t: p.t }));
      else if (item.mode === "stroke") layers.push(shape(item, white, "", p.t));
      else layers.push(layer({ d: item.d, fill: rgba(white, dark ? 0.14 : 0.12), stroke: rgba(white, dark ? 0.75 : 0.6), sw: 0.5, css: `mix-blend-mode:${dark ? "screen" : "normal"};`, t: p.t }));
    } else if (item.role === "secondary" && item.tone === "light") layers.push(shape(item, rgba("#FFFFFF", dark ? 0.6 : 0.8), "", p.t));
    else if (item.role === "secondary") layers.push(shape(item, rgba(shadow, 0.28 + (item.z ?? 0) * 0.1), "", p.t));
    else if (item.role === "detail") layers.push(shape(item, rgba(white, 0.4), "", p.t));
    else if (item.role === "cut") layers.push(shape(item, rgba(dark ? "#0B0820" : "#F4EEFB", 0.55), "", p.t));
    else if (item.role === "lit") layers.push(shape(item, rgba("#FFFFFF", dark ? 0.85 : 0.9), "", p.t));
    else if (item.tone === "dark") layers.push(shape(item, rgba("#06040F", 0.62), "", p.t));
    else layers.push(shape(item, rgba(white, 0.9), "", p.t));
  }
  const base = view(`linear-gradient(${Math.round(150 + random() * 60)}deg,${bg1},${bg2})`, bg1, layers, { blend: "overlay", opacity: dark ? 0.3 : 0.22 });
  if (ctx.bare) return base;

  const shade = dark ? "6,4,15" : "255,255,255";
  const k = dark ? 0.62 : 0.7;
  const glass = (alpha: number) => rgba(dark ? "#0A0716" : "#FFFFFF", alpha);
  const blur = "backdrop-filter:blur(3cqw);-webkit-backdrop-filter:blur(3cqw);";
  if (layout.scrim === "bottom") layers.push(plain(`left:0;top:38cqw;width:100%;height:62cqw;background:linear-gradient(180deg,rgba(${shade},0),rgba(${shade},${k}));`));
  if (layout.scrim === "top") layers.push(plain(`left:0;top:0;width:100%;height:62cqw;background:linear-gradient(0deg,rgba(${shade},0),rgba(${shade},${k}));`));
  if (layout.scrim === "left") layers.push(plain(`left:0;top:0;width:52cqw;height:100%;background:linear-gradient(90deg,rgba(${shade},${k}),rgba(${shade},${k * 0.5}) 55%,rgba(${shade},0));`));
  if (layout.sheet) layers.push(plain(`left:0;top:${layout.sheet}cqw;width:100%;height:${100 - layout.sheet}cqw;border-radius:5cqw 5cqw 0 0;background:${glass(dark ? 0.55 : 0.6)};border-top:.3cqw solid ${rgba(white, 0.25)};${blur}`));

  const lines = splitTitle(ctx.heading);
  const latin = isLatin(lines.join(" "));
  const t = layout.title;
  // The pill goes to the first corner that is clear of both the picture's subject and the title.
  const keepOut: Box = layout.sheet ? { x: 0, y: layout.sheet, w: 100, h: 100 - layout.sheet } : t;
  const order: PillKey[] = [layout.pill, ...(["tl", "tr", "bl", "br"] as const).filter((key) => key !== layout.pill)];
  const pill = order.find((key) => !hitsCircle(p.subject, PILLS[key].r) && !hitsBox(PILLS[key].r, keepOut)) ?? layout.pill;
  return {
    ...base,
    title: titleBox(lines, t, { fam: latin ? MONO : SANS, fw: latin ? 700 : 600, color: white, ls: -0.01, lh: 1.08, max: t.max, vertical: t.vertical, align: t.align, anchor: t.anchor }),
    caption: {
      text: `FM ${ctx.station.freq} · ${ctx.station.name}`,
      css: `${PILLS[pill].css}padding:1.1cqw 2.6cqw;border-radius:99cqw;background:${rgba(white, 0.12)};border:.25cqw solid ${rgba(white, 0.26)};backdrop-filter:blur(1.5cqw);-webkit-backdrop-filter:blur(1.5cqw);color:${white};font-family:${MONO};font-size:3.2cqw;font-weight:500;letter-spacing:.06em;`,
    },
  };
};
