// Placing a motif on the card: the window it fills, how far it is zoomed, and the layers it is drawn as.
import { clamp, r2 } from "./color";
import type { Layer, Motif, PictureItem } from "./types";

export type Region = { x: number; y: number; w: number; h: number };
export const FULL: Region = { x: 0, y: 0, w: 100, h: 100 };
export type WindowShape = "full" | "rect" | "round" | "circle" | "arch";

export const layer = (o: Partial<Layer>): Layer => ({ d: "M0 0", fill: "none", stroke: "none", sw: 0, css: "", t: "", ...o });
/** A box with no drawing, only CSS (a gradient, a frame, a label). */
export const plain = (css: string) => layer({ css });
export const shape = (item: PictureItem, color: string, css = "", t = ""): Layer =>
  item.mode === "stroke" ? layer({ d: item.d, stroke: color, sw: item.sw ?? 0.35, css, t }) : layer({ d: item.d, fill: color, css, t });

export type PlaceOptions = {
  zoom?: number;
  /** A point on the card where the motif's view point should land (default: the window's centre). */
  target?: [number, number] | null;
  shape?: WindowShape;
  flip?: boolean;
  /** A deliberate close crop: the subject may leave the window. */
  crop?: boolean;
  /** Keep the subject clear of this many cqw along the top (the station pill). */
  safeTop?: number | null;
  /** Shift by this much (cqw), for off-register ink and offset shadows. */
  offset?: [number, number];
};
export type Placement = { t: string; clip: string; subject: { x: number; y: number; r: number } };

/**
 * The motif is scaled to cover the window (zoom > 1 crops tighter) and slid so the target holds its view
 * point, never so far that the window shows bare background. Unless the layout asks for a deliberate crop,
 * the zoom is lowered until the subject is whole inside the window.
 */
export function placeMotif(motif: Motif, region: Region, o: PlaceOptions): Placement {
  const cx = region.x + region.w / 2;
  const cy = region.y + region.h / 2;
  const target = o.target ?? [cx, cy];
  const [viewX, viewY] = motif.view;
  const subjectRadius = motif.fr ?? 18;
  const side = Math.max(region.w, region.h) / 100;

  const at = (zoom: number) => {
    const s = side * zoom;
    let ty = clamp(target[1] - s * viewY, region.y + region.h - 100 * s, region.y);
    if (o.safeTop != null) {
      const top = ty + s * (motif.focus[1] - subjectRadius);
      if (top < o.safeTop) ty = Math.min(region.y, ty + (o.safeTop - top));
    }
    return { s, tx: clamp(target[0] - s * viewX, region.x + region.w - 100 * s, region.x), ty };
  };
  const whole = (p: ReturnType<typeof at>) => {
    const px = p.tx + p.s * motif.focus[0];
    const py = p.ty + p.s * motif.focus[1];
    const rr = p.s * subjectRadius;
    return px - rr >= region.x - 1 && px + rr <= region.x + region.w + 1 && py - rr >= Math.max(region.y, o.safeTop ?? 0) - 1 && py + rr <= region.y + region.h + 1;
  };

  let zoom = motif.noZoom ? Math.min(o.zoom ?? 1, 1) : o.zoom ?? 1;
  let p = at(zoom);
  while (!o.crop && zoom > 1 && !whole(p)) { zoom = Math.max(1, r2(zoom - 0.1)); p = at(zoom); }

  const [dx, dy] = o.offset ?? [0, 0];
  const tx = p.tx + dx;
  const ty = p.ty + dy;
  const mirror = o.flip ? `translate(${r2(cx)}cqw,0) scale(-1,1) translate(${r2(-cx)}cqw,0) ` : "";
  const t = `transform:${mirror}translate(${r2(tx)}cqw,${r2(ty)}cqw) scale(${r2(p.s)});transform-origin:0 0;`;
  const sx = tx + p.s * motif.focus[0];
  return { t, clip: clipFor(region, o.shape ?? "full"), subject: { x: o.flip ? 2 * cx - sx : sx, y: ty + p.s * motif.focus[1], r: p.s * subjectRadius } };
}

function clipFor(region: Region, windowShape: WindowShape): string {
  if (windowShape === "full") return "";
  if (windowShape === "circle") return `clip-path:circle(${r2(region.w / 2)}cqw at ${r2(region.x + region.w / 2)}cqw ${r2(region.y + region.h / 2)}cqw);`;
  const corners = windowShape === "arch" ? `${r2(region.w / 2)}cqw ${r2(region.w / 2)}cqw 0 0` : windowShape === "round" ? "2.4cqw" : "0";
  return `clip-path:inset(${r2(region.y)}cqw ${r2(100 - region.x - region.w)}cqw ${r2(100 - region.y - region.h)}cqw ${r2(region.x)}cqw round ${corners});`;
}
