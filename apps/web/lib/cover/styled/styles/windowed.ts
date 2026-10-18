// Five styles that share the poster's window layouts and differ in how the roles are drawn: line art, neon,
// blueprint, cut paper and risograph.
import { FULL, layer, placeMotif, plain, shape, type Placement } from "../art";
import { hashString, hsl, mix, rgba } from "../color";
import { hues } from "../hues";
import type { Motif, StyleContext } from "../types";
import { frameCss, MONO, SANS, view, WINDOW_LAYOUTS, windowFinish, type StyleFn, type WindowLayout } from "./kit";

/** Places the motif in the layout's window (or the whole card, bare), optionally shifted for offset ink or shadows. */
function inWindow(motif: Motif, layout: WindowLayout, ctx: StyleContext, flip: boolean, offset?: [number, number]): Placement {
  return placeMotif(motif, ctx.bare ? FULL : layout.reg, { zoom: ctx.bare ? 1 : layout.zoom, shape: ctx.bare ? "rect" : layout.shape, flip, crop: layout.crop, offset });
}

const lineArt: StyleFn = (motif, random, ctx) => {
  const { h, ha } = hues(ctx.station.hue, random);
  const paper = hsl(h, 30, 93);
  const win = hsl(ha, 42, 88);
  const fill = hsl(ha + 20, 72, 70);
  const ink = hsl(h, 45, 16);
  const layout = WINDOW_LAYOUTS[ctx.layout];
  const flip = random() < 0.5;
  const p = inWindow(motif, layout, ctx, flip);
  const offFill = inWindow(motif, layout, ctx, flip, [1.3, 1.3]);
  const layers = [plain(`${p.clip}background:${win};`)];
  for (const item of motif.items) {
    const outline = (color: string, sw: number) => layer({ d: item.d, stroke: color, sw, css: p.clip, t: p.t });
    if (item.role === "primary") {
      if (item.mode !== "stroke") layers.push(layer({ d: item.d, fill, css: offFill.clip, t: offFill.t }));
      layers.push(outline(ink, item.mode === "stroke" ? (item.sw ?? 1) * 0.8 : 0.85));
    } else if (item.role === "secondary") layers.push(layer({ d: item.d, fill: item.tone === "light" ? "#FFFFFF" : win, stroke: ink, sw: 0.85, css: p.clip, t: p.t }));
    else if (item.role === "detail") layers.push(item.mode === "stroke" ? outline(ink, Math.min(0.45, item.sw ?? 0.4)) : layer({ d: item.d, fill: ink, css: p.clip, t: p.t }));
    else if (item.role === "cut") layers.push(layer({ d: item.d, fill: win, css: p.clip, t: p.t }));
    else if (item.role === "lit") layers.push(layer({ d: item.d, fill, css: p.clip, t: p.t }));
    else layers.push(layer({ d: item.d, fill: ink, css: p.clip, t: p.t }));
  }
  if (!ctx.bare) layers.push(plain(frameCss(layout.reg, layout.shape, ink, 0.7)));
  return windowFinish(view(paper, paper, layers, { blend: "multiply", opacity: 0.12 }), layout, ctx, { ink, block: paper, fam: SANS, fw: 800, famLatin: SANS, fwLatin: 800 });
};

const neon: StyleFn = (motif, random, ctx) => {
  const { h, ha } = hues(ctx.station.hue, random);
  const bg = hsl(h, 55, 6);
  const win = hsl(h, 50, 8);
  const n1 = hsl(ha, 100, 64);
  const n2 = hsl(h + 60, 100, 62);
  const layout = WINDOW_LAYOUTS[ctx.layout];
  const p = inWindow(motif, layout, ctx, random() < 0.5);
  const glow = (color: string, k: number) => `${p.t}filter:drop-shadow(0 0 ${0.7 * k}cqw ${color}) drop-shadow(0 0 ${1.8 * k}cqw ${rgba(color, 0.55)});`;
  const grid = `background-image:linear-gradient(${rgba(n2, 0.16)} .25cqw,transparent .25cqw),linear-gradient(90deg,${rgba(n2, 0.16)} .25cqw,transparent .25cqw);background-size:6.4cqw 6.4cqw;`;
  const layers = [plain(`${p.clip}background-color:${win};${grid}`)];
  for (const item of motif.items) {
    if (item.role === "primary") {
      layers.push(item.mode === "stroke"
        ? layer({ d: item.d, stroke: n1, sw: (item.sw ?? 1) * 0.8, css: p.clip, t: glow(n1, 1) })
        : layer({ d: item.d, fill: rgba(n1, 0.2), stroke: n1, sw: 0.9, css: p.clip, t: glow(n1, 1) }));
    } else if (item.role === "secondary") layers.push(layer({ d: item.d, fill: win, stroke: n2, sw: 0.8, css: p.clip, t: glow(n2, 0.8) }));
    else if (item.role === "detail") {
      layers.push(item.mode === "stroke"
        ? layer({ d: item.d, stroke: rgba(n2, 0.8), sw: 0.4, css: p.clip, t: glow(n2, 0.5) })
        : layer({ d: item.d, fill: "#FFFFFF", css: p.clip, t: p.t }));
    } else if (item.role === "cut") layers.push(layer({ d: item.d, fill: win, css: p.clip, t: p.t }));
    else if (item.role === "lit") layers.push(layer({ d: item.d, fill: n2, css: p.clip, t: glow(n2, 0.8) }));
    else layers.push(layer({ d: item.d, fill: n1, css: p.clip, t: glow(n1, 0.8) }));
  }
  if (!ctx.bare) layers.push(plain(frameCss(layout.reg, layout.shape, rgba(n2, 0.6), 0.35)));
  return windowFinish(view(bg, bg, layers, { blend: "overlay", opacity: 0.18 }), layout, ctx, {
    ink: n2, color: "#FFFFFF", block: bg, fam: SANS, fw: 700, famLatin: MONO, fwLatin: 700,
    extra: `text-shadow:0 0 1.6cqw ${rgba(n1, 0.9)},0 0 .4cqw ${rgba(n1, 0.8)};`,
    blockExtra: `box-shadow:0 0 2cqw ${rgba(n2, 0.4)};`,
  });
};

const blueprint: StyleFn = (motif, random, ctx) => {
  hues(ctx.station.hue, random);
  const bg = hsl(214 + (random() * 2 - 1) * 6, 72, 30 + random() * 5);
  const line = hsl(200, 80, 92);
  const layout = WINDOW_LAYOUTS[ctx.layout];
  const p = inWindow(motif, layout, ctx, random() < 0.5);
  const dashed = `${p.t}stroke-dasharray:1.6 1.1;`;
  const sheet = `background-image:linear-gradient(${rgba(line, 0.1)} .3cqw,transparent .3cqw),linear-gradient(90deg,${rgba(line, 0.1)} .3cqw,transparent .3cqw);background-size:6.25cqw 6.25cqw;`;
  const layers = [plain(`left:0;top:0;width:100%;height:100%;${sheet}`), plain(`${p.clip}background:${rgba(line, 0.05)};`)];
  for (const item of motif.items) {
    if (item.role === "primary") {
      layers.push(item.mode === "stroke"
        ? layer({ d: item.d, stroke: line, sw: (item.sw ?? 1) * 0.5, css: p.clip, t: p.t })
        : layer({ d: item.d, fill: rgba(line, 0.14), stroke: line, sw: 0.7, css: p.clip, t: p.t }));
    } else if (item.role === "secondary") layers.push(layer({ d: item.d, fill: bg, stroke: line, sw: 0.55, css: p.clip, t: p.t }));
    else if (item.role === "detail") {
      layers.push(item.mode === "stroke"
        ? layer({ d: item.d, stroke: rgba(line, 0.85), sw: 0.3, css: p.clip, t: dashed })
        : layer({ d: item.d, fill: line, css: p.clip, t: p.t }));
    } else if (item.role === "cut") layers.push(layer({ d: item.d, fill: bg, css: p.clip, t: p.t }));
    else if (item.role === "lit") layers.push(layer({ d: item.d, fill: rgba(line, 0.85), css: p.clip, t: p.t }));
    else layers.push(layer({ d: item.d, fill: line, css: p.clip, t: p.t }));
  }
  if (!ctx.bare) layers.push(plain(frameCss(layout.reg, layout.shape, line, 0.35)));
  const figure = `FIG.${String(1 + (hashString(ctx.heading) % 90)).padStart(2, "0")}`;
  return windowFinish(view(bg, bg, layers, { blend: "overlay", opacity: 0.14 }), layout, ctx, { ink: line, block: bg, fam: SANS, fw: 700, famLatin: MONO, fwLatin: 700, ls: 0.02, caption: figure });
};

const cutPaper: StyleFn = (motif, random, ctx) => {
  const { h, ha } = hues(ctx.station.hue, random);
  const paper = hsl(h, 55, 90);
  const win = hsl(ha, 60, 82);
  const colours = { c1: hsl(ha, 78, 58), c2: hsl(h, 62, 46), c3: hsl(h + 40, 74, 62), c4: hsl(h + 80, 80, 74), dark: hsl(h, 42, 16), light: hsl(h, 50, 96) };
  const layout = WINDOW_LAYOUTS[ctx.layout];
  const flip = random() < 0.5;
  const p = inWindow(motif, layout, ctx, flip);
  const cast = inWindow(motif, layout, ctx, flip, [1.1, 1.5]);
  const layers = [plain(`${p.clip}background:${win};`)];
  const shadow = (d: string) => layers.push(layer({ d, fill: rgba(colours.dark, 0.3), css: cast.clip, t: cast.t }));
  for (const item of motif.items) {
    if (item.role === "primary") {
      if (item.mode !== "stroke") shadow(item.d);
      layers.push(shape(item, colours.c1, p.clip, p.t));
    } else if (item.role === "secondary") {
      shadow(item.d);
      layers.push(shape(item, item.tone === "light" ? colours.light : [colours.c2, colours.dark, colours.c3, colours.dark][Math.min(3, item.z ?? 0)], p.clip, p.t));
    } else if (item.role === "detail") layers.push(shape(item, colours.light, `${p.clip}opacity:.8;`, p.t));
    else if (item.role === "cut") layers.push(shape(item, win, p.clip, p.t));
    else if (item.role === "lit") layers.push(shape(item, colours.c4, p.clip, p.t));
    else layers.push(shape(item, item.tone === "dark" ? colours.dark : colours.c3, p.clip, p.t));
  }
  return windowFinish(view(paper, paper, layers, { blend: "multiply", opacity: 0.2 }), layout, ctx, {
    ink: colours.dark, block: colours.c4, fam: SANS, fw: 900, famLatin: SANS, fwLatin: 900, blockExtra: `box-shadow:1cqw 1.2cqw 0 ${rgba(colours.dark, 0.25)};`,
  });
};

const INK_PAIRS = [[348, 222], [18, 192], [300, 205], [40, 330]] as const;
const dots = (size: number, k: number) =>
  `-webkit-mask-image:radial-gradient(circle,#000 ${k}%,transparent ${k + 4}%);mask-image:radial-gradient(circle,#000 ${k}%,transparent ${k + 4}%);-webkit-mask-size:${size}cqw ${size}cqw;mask-size:${size}cqw ${size}cqw;`;

const risograph: StyleFn = (motif, random, ctx) => {
  hues(ctx.station.hue, random);
  const [hueA, hueB] = INK_PAIRS[Math.floor(random() * INK_PAIRS.length)];
  const paper = hsl(40, 35, 94);
  const inkA = hsl(hueA, 90, 58);
  const inkB = hsl(hueB, 82, 33);
  const layout = WINDOW_LAYOUTS[ctx.layout];
  const flip = random() < 0.5;
  const a = inWindow(motif, layout, ctx, flip);
  const b = inWindow(motif, layout, ctx, flip, [0.9, 0.7]);
  const layers = [plain(`${a.clip}background:${mix(paper, "#000000", 0.04)};`)];
  const multiply = (p: Placement, extra = "") => `${p.clip}mix-blend-mode:multiply;${extra}`;
  for (const item of motif.items) {
    if (item.role === "primary") layers.push(shape(item, inkA, multiply(a), a.t));
    else if (item.role === "secondary") {
      const second = (item.z ?? 0) % 2 === 0;
      const p = second ? b : a;
      layers.push(shape(item, second ? inkB : inkA, multiply(p, (item.z ?? 0) >= 2 ? dots(2.4, 40) : ""), p.t));
    } else if (item.role === "detail") layers.push(shape(item, inkB, multiply(b, "opacity:.85;"), b.t));
    else if (item.role === "cut" || item.role === "lit") layers.push(shape(item, paper, a.clip, a.t));
    else layers.push(shape(item, inkB, multiply(b), b.t));
  }
  return windowFinish(view(paper, paper, layers, { blend: "multiply", opacity: 0.38 }), layout, ctx, {
    ink: inkB, color: inkB, block: paper, fam: SANS, fw: 900, famLatin: SANS, fwLatin: 900, extra: "mix-blend-mode:multiply;",
  });
};

export const WINDOWED_STYLES = { line: lineArt, neon, blue: blueprint, cut: cutPaper, riso: risograph } satisfies Record<string, StyleFn>;
