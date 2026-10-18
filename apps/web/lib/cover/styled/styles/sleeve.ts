// Sleeve: a record cover. Paper, a halftone print of the picture, ruled frame, the title on the paper.
import { FULL, layer, placeMotif, plain, shape, type Region } from "../art";
import { hsl, mix, r2 } from "../color";
import { hues } from "../hues";
import { emWidth, fitSize, isLatin, splitTitle, titleBox, type TitleOptions, type TitleSpec } from "../text";
import { MONO, SERIF, view, type StyleFn } from "./kit";

type SleeveLayout = {
  reg: Region;
  shape: "rect" | "circle";
  zoom?: number;
  rule?: string;
  /** The title is paper-coloured with an ink outline, over the picture. */
  knock?: boolean;
  /** The big station frequency on top of the picture instead of a caption. */
  numerals?: boolean;
  title: TitleSpec;
  /** Position of the "FM 93.1 · 名" caption; capTag puts it on a small label, capShort drops the name. */
  caption?: string;
  captionTag?: boolean;
  captionShort?: boolean;
};
export const SLEEVE_LAYOUTS: SleeveLayout[] = [
  { reg: { x: 4, y: 4, w: 92, h: 66 }, shape: "rect", rule: "left:4cqw;top:69.6cqw;width:92cqw;height:.9cqw;", title: { x: 9, y: 72, w: 82, h: 16, align: "left", anchor: "center", max: 9, lh: 1 }, caption: "right:9cqw;bottom:6cqw;" },
  { reg: { x: 4, y: 35, w: 92, h: 61 }, shape: "rect", rule: "left:4cqw;top:34.6cqw;width:92cqw;height:.9cqw;", title: { x: 9, y: 8, w: 82, h: 24, align: "left", anchor: "center", max: 15, lh: 1 }, caption: "right:8cqw;bottom:7cqw;", captionTag: true },
  { reg: { x: 34, y: 4, w: 62, h: 92 }, shape: "rect", rule: "left:33.6cqw;top:4cqw;width:.9cqw;height:92cqw;", title: { x: 8, y: 8, w: 22, h: 72, vertical: true, max: 19, lh: 1 }, caption: "left:8cqw;bottom:6.5cqw;", captionShort: true },
  { reg: { x: 4, y: 30, w: 92, h: 66 }, shape: "rect", rule: "left:4cqw;top:29.6cqw;width:92cqw;height:.9cqw;", numerals: true, title: { x: 56, y: 8, w: 36, h: 19, align: "right", anchor: "center", max: 8, lh: 1.05 } },
  { reg: { x: 4, y: 4, w: 92, h: 92 }, shape: "rect", zoom: 1.15, knock: true, title: { x: 9, y: 54, w: 82, h: 38, align: "left", anchor: "bottom", max: 22, lh: 0.95 }, caption: "right:8cqw;top:7.5cqw;", captionTag: true },
];

const dots = (size: number, k: number) =>
  `-webkit-mask-image:radial-gradient(circle,#000 ${k}%,transparent ${k + 4}%);mask-image:radial-gradient(circle,#000 ${k}%,transparent ${k + 4}%);-webkit-mask-size:${size}cqw ${size}cqw;mask-size:${size}cqw ${size}cqw;`;

export const sleeve: StyleFn = (motif, random, ctx) => {
  const { h, ha } = hues(ctx.station.hue, random);
  const paper = hsl(38 + (h - 38) * 0.12, 40, 88);
  const ink = hsl(h, 35, 12);
  const s1 = hsl(h, 72, 47);
  const s2 = hsl(ha, 74, 55);
  const layout = SLEEVE_LAYOUTS[ctx.layout];
  const flip = random() < 0.5;
  const dx = 1 + random() * 0.8;
  const dy = 0.7 + random() * 0.8;
  const bg = mix(paper, s1, 0.1);
  const options = { zoom: ctx.bare ? 1 : layout.zoom ?? 1, shape: ctx.bare ? ("rect" as const) : layout.shape, flip };
  const region = ctx.bare ? FULL : layout.reg;
  const p = placeMotif(motif, region, options);
  const print = placeMotif(motif, region, { ...options, offset: [dx, dy] });
  const layers = [plain(`${p.clip}background:${bg};`)];
  for (const item of motif.items) {
    if (item.role === "primary") {
      layers.push(shape(item, mix(s1, bg, 0.18), `${p.clip}mix-blend-mode:multiply;`, p.t));
      layers.push(shape(item, ink, `${print.clip}${dots(3, 38)}opacity:.55;`, print.t));
    } else if (item.role === "secondary" && item.tone === "light") {
      layers.push(shape(item, mix(paper, "#FFFFFF", 0.5), p.clip, p.t), layer({ d: item.d, stroke: ink, sw: 0.5, css: p.clip, t: p.t }));
    } else if (item.role === "secondary") layers.push(shape(item, mix(ink, bg, 0.04 + (item.z ?? 0) * 0.18), p.clip, p.t));
    else if (item.role === "detail") layers.push(shape(item, ink, `${p.clip}opacity:.4;`, p.t));
    else if (item.role === "cut" || item.role === "lit") layers.push(shape(item, bg, p.clip, p.t));
    else layers.push(shape(item, item.tone === "dark" ? ink : s2, `${p.clip}${item.tone === "dark" ? "" : "mix-blend-mode:multiply;"}`, p.t));
  }
  const base = view(paper, paper, layers, { blend: "multiply", opacity: 0.28 });
  if (ctx.bare) return base;

  if (layout.rule) layers.push(plain(`${layout.rule}background:${ink};`));
  layers.push(plain(`left:4cqw;top:4cqw;width:92cqw;height:92cqw;box-sizing:border-box;border:.7cqw solid ${ink};`));
  const lines = splitTitle(ctx.heading);
  const latin = isLatin(lines.join(" "));
  const t = layout.title;
  const style: TitleOptions = { fam: SERIF, fw: latin ? 400 : 900, color: ink, ls: latin ? 0 : -0.01, lh: t.lh, max: t.max, vertical: t.vertical, align: t.align, anchor: t.anchor };
  if (layout.knock) {
    const size = fitSize(lines, t, style);
    style.color = paper;
    style.extra = `-webkit-text-stroke:${r2(size * 0.09)}cqw ${ink};paint-order:stroke fill;`;
  }
  let caption = { text: "", css: "" };
  let caption2 = { text: "", css: "" };
  if (layout.numerals) {
    const size = r2(Math.min(24, 46 / emWidth(ctx.station.freq, 0.02)) * 0.95);
    caption = { text: ctx.station.freq, css: `left:8cqw;top:${r2(17 - size * 0.5)}cqw;font-family:${MONO};font-weight:700;font-size:${size}cqw;line-height:1;letter-spacing:.02em;color:${ink};` };
    caption2 = { text: `${ctx.station.name} · FM`, css: `left:8.5cqw;top:23.6cqw;font-size:3cqw;font-weight:600;letter-spacing:.14em;color:${ink};` };
  }
  if (layout.caption) {
    const tag = layout.captionTag ? `background:${paper};padding:.9cqw 1.8cqw;border:.4cqw solid ${ink};` : "";
    caption = { text: `FM ${ctx.station.freq}${layout.captionShort ? "" : `  ·  ${ctx.station.name}`}`, css: `${layout.caption}${tag}font-family:${MONO};font-weight:700;font-size:3cqw;letter-spacing:.14em;color:${ink};` };
  }
  return { ...base, title: titleBox(lines, t, style), caption, caption2 };
};
