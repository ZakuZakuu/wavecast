import { r2 } from "./color";
import type { TextBox } from "./types";

const CJK = /[㐀-鿿぀-ヿ가-힯]/;

/** Advance width of a glyph in em, close enough to fit a title in a box whatever the font. */
function advance(ch: string): number {
  if (/[㐀-鿿぀-ヿ가-힯\u3000-〿！-｠]/.test(ch)) return 1;
  if (/[A-Z]/.test(ch)) return 0.7;
  if (/[ijl]/.test(ch)) return 0.3;
  if (/[mw]/.test(ch)) return 0.86;
  if (/[a-z]/.test(ch)) return 0.57;
  if (/[0-9]/.test(ch)) return 0.6;
  if (ch === " ") return 0.3;
  if (ch === "-" || ch === "'") return 0.38;
  if (ch === "." || ch === "·") return 0.3;
  return 0.6;
}

export function emWidth(line: string, letterSpacing = 0): number {
  const glyphs = [...line];
  return glyphs.reduce((sum, ch) => sum + advance(ch), 0) + Math.max(0, glyphs.length - 1) * letterSpacing;
}

export const isLatin = (text: string) => /^[\p{ASCII}\s]+$/u.test(text);
const isCjk = (text: string) => text.length > 0 && [...text].every((ch) => CJK.test(ch));

/** Lines for a title: the editor's own breaks are kept; a long single line is split near its middle (never leaving one orphan). */
export function splitTitle(heading: string): string[] {
  let lines = heading.split("\n").map((line) => line.trim()).filter(Boolean);
  if (lines.length === 1 && emWidth(lines[0]) > 6.4) {
    const text = lines[0];
    const glyphs = [...text];
    if (text.includes(" ")) {
      let best = -1;
      let distance = Infinity;
      glyphs.forEach((ch, i) => {
        if (ch === " " && Math.abs(i - glyphs.length / 2) < distance) {
          distance = Math.abs(i - glyphs.length / 2);
          best = i;
        }
      });
      lines = [glyphs.slice(0, best).join(""), glyphs.slice(best + 1).join("")];
    } else {
      let cut = Math.ceil(glyphs.length / 2);
      while (cut < glyphs.length - 1 && /[，。、：；？！」』）]/.test(glyphs[cut])) cut += 1;
      lines = [glyphs.slice(0, cut).join(""), glyphs.slice(cut).join("")];
    }
  }
  return lines.slice(0, 3);
}

export type Zone = { x: number; y: number; w?: number; h?: number };
/** Where a layout puts the title: the zone, the largest size, and how the lines sit in it. */
export type TitleSpec = { x: number; y: number; w: number; h: number; max: number; lh?: number; align?: "left" | "center" | "right"; anchor?: "top" | "center" | "bottom"; vertical?: boolean };
export type TitleOptions = {
  fam: string;
  fw: number;
  color: string;
  ls?: number;
  lh?: number;
  max: number;
  vertical?: boolean;
  align?: "left" | "center" | "right";
  anchor?: "top" | "center" | "bottom";
  /** Shrink-wrapped at x/y instead of filling a box. */
  free?: boolean;
  extra?: string;
};

/** Font size (cqw) that fits the lines in the zone; heavy weights run wider, so they get a margin. */
export function fitSize(lines: string[], zone: { w: number; h: number }, o: Pick<TitleOptions, "ls" | "lh" | "max" | "vertical" | "fw">): number {
  const lh = o.lh ?? 1.05;
  const longest = Math.max(...lines.map((line) => emWidth(line, o.ls)));
  const size = o.vertical
    ? Math.min(o.max, zone.h / longest, zone.w / (lines.length * lh))
    : Math.min(o.max, zone.w / longest, zone.h / (lines.length * lh));
  return r2(size * 0.95 * (o.fw >= 800 ? 0.93 : 1));
}

/**
 * Positions a title in a zone. A single CJK line set vertically is stacked one character per row (any font
 * can do that); other vertical text is turned sideways.
 */
export function titleBox(lines: string[], zone: Zone, o: TitleOptions): TextBox & { size: number } {
  const lh = o.lh ?? 1.05;
  const box = { w: zone.w ?? 60, h: zone.h ?? 20 };
  const stacked = Boolean(o.vertical) && lines.length === 1 && isCjk(lines[0]);
  let text = lines.join("\n");
  let size: number;
  if (stacked) {
    const chars = [...lines[0]];
    text = chars.join("\n");
    size = r2(Math.min(o.max, box.h / (chars.length * lh), box.w) * 0.95);
  } else {
    size = fitSize(lines, box, o);
  }
  const font = `font-family:${o.fam};font-size:${size}cqw;font-weight:${o.fw};line-height:${lh};letter-spacing:${stacked ? 0 : o.ls ?? 0}em;color:${o.color};white-space:pre;${o.extra ?? ""}`;
  const place = `left:${zone.x}cqw;top:${zone.y}cqw;`;
  const sized = `width:${box.w}cqw;height:${box.h}cqw;`;
  const justify = { top: "flex-start", center: "center", bottom: "flex-end" }[o.anchor ?? "top"];
  const css = o.free
    ? place + font
    : o.vertical && !stacked
      ? `${place}${sized}writing-mode:vertical-rl;text-orientation:sideways;${font}`
      : `${place}${sized}display:flex;flex-direction:column;justify-content:${justify};text-align:${stacked ? "center" : o.align ?? "left"};${font}`;
  return { text, css, size };
}
