// Scene: a sky with a sun, silhouettes in front, and the title on a sticker, ribbon, bar, postcard or stroke lettering.
import { FULL, layer, placeMotif, plain, shape, type Region, type WindowShape } from "../art";
import { hsl, mix, r2, rgba } from "../color";
import { hues } from "../hues";
import { circle } from "../shapes";
import { fitSize, splitTitle, titleBox } from "../text";
import type { CoverView, PictureItem } from "../types";
import { MONO, SANS, view, type StyleFn } from "./kit";

type SceneKind = "sticker" | "ribbon" | "bar" | "postcard" | "travel";
type SceneLayout = { kind: SceneKind; zoom?: number; target?: [number, number]; reg?: Region; shape?: WindowShape };
export const SCENE_LAYOUTS: SceneLayout[] = [
  { kind: "sticker", zoom: 1.05 },
  { kind: "ribbon", zoom: 1.3, target: [50, 48] },
  { kind: "bar", zoom: 1 },
  { kind: "postcard", reg: { x: 7, y: 7, w: 86, h: 64 }, shape: "round" },
  { kind: "travel", zoom: 1.1 },
];

export const scene: StyleFn = (motif, random, ctx) => {
  const { h, ha } = hues(ctx.station.hue, random);
  const day = random() < 0.45;
  const sky = [day ? hsl(h, 55, 74) : hsl(h, 50, 17), day ? hsl(ha, 70, 83) : hsl(h + 10, 55, 33), day ? hsl(ha, 75, 89) : hsl(ha, 72, 60)];
  const sun = hsl(ha, 82, day ? 64 : 70);
  const ink = hsl(h, 40, 12);
  const cream = hsl(h, 45, 93);
  const sil = [hsl(h, 36, day ? 56 : 30), hsl(h, 38, day ? 40 : 21), hsl(h, 40, day ? 26 : 12), hsl(h, 45, day ? 16 : 7)];
  const layout = SCENE_LAYOUTS[ctx.layout];
  const flip = random() < 0.5;
  const skyGradient = `linear-gradient(180deg,${sky[0]} 0%,${sky[1]} 58%,${sky[2]} 100%)`;
  const windowed = !ctx.bare && layout.reg !== undefined;
  const p = placeMotif(motif, windowed ? layout.reg! : FULL, { zoom: ctx.bare ? 1 : layout.zoom ?? 1, target: ctx.bare ? null : layout.target, shape: windowed ? layout.shape : "full", flip });
  const rootBg = !windowed ? skyGradient : layout.kind === "postcard" ? cream : sil[3];

  const layers = windowed ? [plain(`${p.clip}background:${skyGradient};`)] : [];
  layers.push(layer({ d: circle(motif.focus[0], motif.focus[1], 30), fill: rgba(sun, 0.5), css: `${p.clip}filter:blur(7cqw);`, t: p.t }));
  const of = (role: PictureItem["role"]) => motif.items.filter((item) => item.role === role);
  of("primary").forEach((item) => layers.push(shape(item, sun, p.clip, p.t)));
  of("cut").forEach((item) => layers.push(shape(item, sky[1], p.clip, p.t)));
  of("lit").forEach((item) => layers.push(shape(item, mix(sun, "#FFFFFF", 0.45), p.clip, p.t)));
  of("detail").forEach((item) => layers.push(shape(item, rgba("#FFFFFF", day ? 0.7 : 0.55), p.clip, p.t)));
  const silhouettes = of("secondary");
  silhouettes.forEach((item, i) => {
    if (item.tone === "light") return layers.push(shape(item, mix(sky[2], "#FFFFFF", 0.55), p.clip, p.t));
    const depth = silhouettes.length === 1 ? 2 : Math.round((i / Math.max(1, silhouettes.length - 1)) * 3);
    layers.push(shape(item, sil[Math.min(sil.length - 1, depth)], p.clip, p.t));
  });
  of("accent").forEach((item) => layers.push(shape(item, item.tone === "dark" ? sil[3] : mix(sun, "#FFFFFF", 0.4), p.clip, p.t)));
  const base = view(rootBg, sil[3], layers, { blend: "overlay", opacity: 0.2 });
  if (ctx.bare) return base;

  const lines = splitTitle(ctx.heading);
  const style = { fam: SANS, fw: 700, lh: 1.1, ls: 0 };
  const freq = `FM ${ctx.station.freq}`;
  const small = (position: string, color: string, extra = "", size = 3.2, spacing = 0.06) =>
    `${position}font-family:${MONO};font-size:${size}cqw;font-weight:500;color:${color};letter-spacing:${spacing}em;${extra}`;
  const out = (title: CoverView["title"], caption: CoverView["caption"]): CoverView => ({ ...base, title, caption });

  switch (layout.kind) {
    case "sticker": {
      const size = fitSize(lines, { w: 62, h: 22 }, { max: 12, lh: 1.1, fw: 700 });
      const sticker = `box-sizing:border-box;padding:${r2(size * 0.3)}cqw ${r2(size * 0.5)}cqw;border-radius:2cqw;background:rgba(255,252,246,.94);box-shadow:0 .8cqw 2.4cqw rgba(0,0,0,.18);`;
      const title = titleBox(lines, { x: 6, y: 6 }, { ...style, free: true, color: ink, max: 12, extra: sticker });
      return out({ ...title, css: title.css.replace(/font-size:[\d.]+cqw/, `font-size:${size}cqw`) }, { text: freq, css: small("right:6cqw;bottom:5cqw;", "rgba(255,255,255,.85)") });
    }
    case "ribbon":
      layers.push(plain("left:-6cqw;top:41cqw;width:112cqw;height:18cqw;transform:rotate(-4deg);background:rgba(255,252,246,.95);box-shadow:0 .8cqw 2.4cqw rgba(0,0,0,.2);"));
      return out(
        titleBox(lines, { x: 9, y: 41, w: 82, h: 18 }, { ...style, color: ink, max: 14, align: "center", anchor: "center", extra: "transform:rotate(-4deg);" }),
        { text: `${freq} · ${ctx.station.name}`, css: small("left:6cqw;bottom:5cqw;", "rgba(255,255,255,.88)", "text-shadow:0 0 1.6cqw rgba(0,0,0,.5);") },
      );
    case "bar":
      layers.push(plain(`left:0;top:74cqw;width:100%;height:26cqw;background:${rgba(sil[3], 0.86)};`));
      return out(
        titleBox(lines, { x: 6, y: 76, w: 66, h: 22 }, { ...style, color: "#FFFFFF", max: 12, align: "left", anchor: "center" }),
        { text: freq, css: small("right:6cqw;bottom:6cqw;", "rgba(255,255,255,.7)", "", 3.4) },
      );
    case "postcard":
      return out(
        titleBox(lines, { x: 7, y: 73, w: 60, h: 20 }, { ...style, color: ink, max: 11, align: "left", anchor: "center" }),
        { text: `${freq}\n${ctx.station.name}`, css: `right:7cqw;bottom:7.5cqw;text-align:right;white-space:pre;font-family:${MONO};font-size:3.2cqw;font-weight:500;line-height:1.4;color:${ink};opacity:.65;letter-spacing:.06em;` },
      );
    default: {
      layers.push(plain(`left:0;top:44cqw;width:100%;height:56cqw;background:linear-gradient(180deg,rgba(0,0,0,0),${rgba(sil[3], 0.55)});`));
      const zone = { x: 6, y: 56, w: 88, h: 36 };
      const size = fitSize(lines, zone, { max: 20, lh: 1.02, fw: 800 });
      const stroke = `-webkit-text-stroke:${r2(size * 0.05)}cqw ${sil[3]};paint-order:stroke fill;text-shadow:0 .6cqw 2.4cqw rgba(0,0,0,.4);`;
      return out(
        titleBox(lines, zone, { ...style, color: cream, fw: 800, lh: 1.02, max: 20, align: "center", anchor: "bottom", extra: stroke }),
        { text: `${freq} · ${ctx.station.name}`, css: small("left:0;width:100%;text-align:center;top:5.5cqw;", "rgba(255,255,255,.92)", "text-shadow:0 0 1.6cqw rgba(0,0,0,.5);", 3.2, 0.14) },
      );
    }
  }
};
