// Poster: ink on tinted paper, the picture printed in one colour that multiplies into the paper.
import { FULL, layer, placeMotif, plain, shape } from "../art";
import { hsl, mix } from "../color";
import { hues } from "../hues";
import { SANS, SERIF, view, WINDOW_LAYOUTS, windowFinish, type StyleFn } from "./kit";

export const poster: StyleFn = (motif, random, ctx) => {
  const { h, ha } = hues(ctx.station.hue, random);
  const paper = hsl(h, 26 + random() * 16, 88 + random() * 5);
  const ink = hsl(h, 32, 13);
  const a1 = hsl(ha, 54 + random() * 14, 46 + random() * 8);
  const a2 = hsl(h, 50, 40);
  const tint = mix(paper, a1, 0.16);
  const flip = random() < 0.5;
  const layout = WINDOW_LAYOUTS[ctx.layout];
  const p = placeMotif(motif, ctx.bare ? FULL : layout.reg, { zoom: ctx.bare ? 1 : layout.zoom, shape: ctx.bare ? "rect" : layout.shape, flip, crop: layout.crop });
  const layers = [plain(`${p.clip}background:${tint};`)];
  for (const item of motif.items) {
    if (item.role === "primary") layers.push(shape(item, a1, `${p.clip}mix-blend-mode:multiply;`, p.t));
    else if (item.role === "secondary" && item.tone === "light") {
      layers.push(shape(item, mix(paper, ink, 0.06), p.clip, p.t), layer({ d: item.d, stroke: ink, sw: 0.4, css: p.clip, t: p.t }));
    } else if (item.role === "secondary") layers.push(shape(item, mix(ink, tint, 0.4 + (item.z ?? 0) * 0.2), p.clip, p.t));
    else if (item.role === "detail") layers.push(shape(item, ink, `${p.clip}opacity:.7;`, p.t));
    else if (item.role === "cut") layers.push(shape(item, tint, p.clip, p.t));
    else if (item.role === "lit") layers.push(shape(item, paper, p.clip, p.t));
    else layers.push(shape(item, item.tone === "dark" ? ink : a2, p.clip, p.t));
  }
  const base = view(paper, paper, layers, { blend: "multiply", opacity: 0.16 });
  const serif = random() < 0.55;
  return windowFinish(base, layout, ctx, { ink, block: paper, fam: serif ? SERIF : SANS, fw: serif ? 900 : 700, famLatin: SERIF, fwLatin: 400, ls: -0.02 });
};

