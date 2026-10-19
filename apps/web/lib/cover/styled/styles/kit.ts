// What the styles share: fonts, the empty view, the five window layouts, frames and the common footer.
import type { Region, WindowShape } from "../art";
import { plain } from "../art";
import { isLatin, splitTitle, titleBox, type TitleSpec } from "../text";
import type { CoverView, Layer, Motif, Rng, StyleContext } from "../types";

export type StyleFn = (motif: Motif, random: Rng, ctx: StyleContext) => CoverView;

// System fonts only: Latin display faces are not loaded, so the serif/numeric tokens stand in.
export const SANS = "var(--font-ui)";
export const SERIF = "var(--font-serif)";
export const MONO = "var(--font-numeric)";

const none = { text: "", css: "" };
export const noGrain = { blend: "normal", opacity: 0 };

export function view(rootBg: string, bg: string, layers: Layer[], grain: CoverView["grain"]): CoverView {
  return { rootBg, bg, layers, grain, title: none, caption: none, caption2: none };
}

export type WindowLayout = {
  reg: Region;
  shape: WindowShape;
  zoom?: number;
  crop?: boolean;
  /** A rule drawn on the layout (CSS, cqw). */
  rule?: string;
  /** A block the title sits on, over the picture. */
  block?: Region;
  title: TitleSpec;
};

/** Five compositions where the picture is a window and the title always has clear ground. Poster and the five windowed styles use them. */
export const WINDOW_LAYOUTS: WindowLayout[] = [
  { reg: { x: 6, y: 14, w: 88, h: 60 }, shape: "round", title: { x: 6, y: 76, w: 88, h: 18, align: "left", anchor: "center", max: 13, lh: 1 } },
  { reg: { x: 34, y: 40, w: 72, h: 72 }, shape: "circle", title: { x: 6, y: 14, w: 88, h: 25, align: "left", anchor: "top", max: 19, lh: 0.95 } },
  { reg: { x: 0, y: 13, w: 70, h: 87 }, shape: "rect", title: { x: 74, y: 14, w: 20, h: 78, vertical: true, max: 20, lh: 1 } },
  { reg: { x: 50, y: 14, w: 44, h: 44 }, shape: "rect", rule: "left:6cqw;top:59.6cqw;width:88cqw;height:.45cqw;", title: { x: 6, y: 61, w: 88, h: 33, align: "left", anchor: "bottom", max: 23, lh: 0.95 } },
  { reg: { x: 0, y: 13, w: 100, h: 87 }, shape: "rect", zoom: 1.7, crop: true, block: { x: 6, y: 58, w: 64, h: 34 }, title: { x: 9.5, y: 61, w: 57, h: 28, align: "left", anchor: "bottom", max: 16, lh: 1 } },
];

export const frameCss = (reg: Region, windowShape: WindowShape, color: string, width: number) =>
  `left:${reg.x}cqw;top:${reg.y}cqw;width:${reg.w}cqw;height:${reg.h}cqw;box-sizing:border-box;border:${width}cqw solid ${color};border-radius:${windowShape === "circle" ? "50%" : windowShape === "round" ? "2.4cqw" : "0"};`;

export type FooterColours = {
  ink: string;
  block: string;
  fam: string;
  fw: number;
  famLatin: string;
  fwLatin: number;
  color?: string;
  ls?: number;
  extra?: string;
  blockExtra?: string;
  /** Replaces "FM 93.1" in the top-left caption. */
  caption?: string;
};

/** Rule, title block, title and the two caption words of a window layout, in the colours the style asks for. */
export function windowFinish(base: CoverView, layout: WindowLayout, ctx: StyleContext, o: FooterColours): CoverView {
  if (ctx.bare) return base;
  const layers = base.layers;
  layers.push(plain(`left:6cqw;top:6.4cqw;width:88cqw;height:.45cqw;background:${o.ink};`));
  if (layout.rule) layers.push(plain(`${layout.rule}background:${o.ink};`));
  if (layout.block) {
    const { x, y, w, h } = layout.block;
    layers.push(plain(`left:${x}cqw;top:${y}cqw;width:${w}cqw;height:${h}cqw;background:${o.block};border:.55cqw solid ${o.ink};box-sizing:border-box;${o.blockExtra ?? ""}`));
  }
  const lines = splitTitle(ctx.heading);
  const latin = isLatin(lines.join(" "));
  const t = layout.title;
  return {
    ...base,
    title: titleBox(lines, t, { fam: latin ? o.famLatin : o.fam, fw: latin ? o.fwLatin : o.fw, color: o.color ?? o.ink, ls: latin ? 0 : o.ls ?? -0.01, lh: t.lh, max: t.max, vertical: t.vertical, align: t.align, anchor: t.anchor, extra: o.extra }),
    caption: { text: o.caption ?? `FM ${ctx.station.freq}`, css: `left:6cqw;top:8.2cqw;font-family:${MONO};font-size:3.4cqw;font-weight:700;letter-spacing:.08em;color:${o.ink};` },
    caption2: { text: ctx.station.name, css: `right:6cqw;top:8.2cqw;font-size:3.4cqw;font-weight:600;letter-spacing:.12em;color:${o.ink};` },
  };
}

