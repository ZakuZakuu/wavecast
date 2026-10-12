// Port of the sample film's makeCover (cover v1). Same station + seed +
// heading => same cover. Returns the layers separately so the composition
// can "build" a cover layer by layer (buildProgress in the sample).
import type { StationId } from "../../../web/lib/stations";
import { r2, rng } from "./anim";
import { SANS, SERIF } from "./fonts";
import { station } from "./stations";

type Palette = { bg: string; p1: string; p2: string; ink: string };

function hsl(h: number, s: number, l: number) {
  h = ((h % 360) + 360) % 360;
  s /= 100;
  l /= 100;
  const k = (n: number) => (n + h / 30) % 12;
  const a = s * Math.min(l, 1 - l);
  const f = (n: number) => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  const x = (v: number) => Math.round(v * 255).toString(16).padStart(2, "0");
  return "#" + x(f(0)) + x(f(8)) + x(f(4));
}
function lum(hex: string) {
  const h = hex.replace("#", "");
  const v = [0, 2, 4]
    .map((i) => parseInt(h.substr(i, 2), 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)));
  return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2];
}
const onC = (hex: string) => (lum(hex) > 0.3 ? "#1C1C1E" : "#FAF8F4");

function palette(R: () => number, hue: number, dark: number): Palette {
  const h = hue + (R() * 2 - 1) * 16,
    acc = h + (R() < 0.5 ? 150 : -150) + (R() * 2 - 1) * 20,
    roll = R();
  if (roll < dark) return { bg: hsl(h, 30 + R() * 15, 11 + R() * 6), p1: hsl(h, 35 + R() * 18, 36 + R() * 12), p2: hsl(18 + R() * 22, 72, 74 + R() * 8), ink: hsl(h, 30, 88) };
  if (roll < dark + (1 - dark) / 2) return { bg: hsl(h, 36 + R() * 22, 85 + R() * 7), p1: hsl(h, 45 + R() * 20, 28 + R() * 10), p2: hsl(acc, 62, 54), ink: hsl(h, 40, 15) };
  return { bg: hsl(h, 45 + R() * 15, 44 + R() * 8), p1: hsl(h, 40, 86 + R() * 6), p2: hsl(h, 50, 15 + R() * 6), ink: hsl(h, 40, 12) };
}

export const circ = (cx: number, cy: number, r: number) =>
  "M" + r2(cx - r) + " " + r2(cy) + "a" + r2(r) + " " + r2(r) + " 0 1 0 " + r2(2 * r) + " 0a" + r2(r) + " " + r2(r) + " 0 1 0 " + r2(-2 * r) + " 0Z";
const box = (x: number, y: number, w: number, h: number) => "M" + r2(x) + " " + r2(y) + "h" + r2(w) + "v" + r2(h) + "h" + r2(-w) + "Z";
const visLen = (s: string) => {
  let n = 0;
  for (const ch of s) n += /[㐀-鿿]/.test(ch) ? 1 : 0.56;
  return n;
};
const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

function textBlock(lines: string[], x: number, y0: number, size: number, lh: number, fill: string, anchor = "start", weight = 700) {
  let s = `<text x="${r2(x)}" y="${r2(y0)}" font-size="${r2(size)}" font-weight="${weight}" fill="${fill}" text-anchor="${anchor}" style="letter-spacing:-0.01em;font-family:${SERIF.replace(/"/g, "'")}">`;
  lines.forEach((l, i) => {
    s += `<tspan x="${r2(x)}" dy="${i ? r2(size * lh) : 0}">${esc(l)}</tspan>`;
  });
  return s + "</text>";
}

export type Cover = { bg: string; parts: string[]; text: string; c: Palette };

export function makeCover(key: StationId, seed: number, heading: string): Cover {
  const st = station(key);
  const R = rng(seed * 2654435761 + st.hue * 97 + 13);
  const tpl = st.tpl[Math.floor(R() * st.tpl.length)],
    c = palette(R, st.hue, st.dark);
  const lines = heading.split("\n"),
    L = lines.length,
    longest = Math.max(1, ...lines.map(visLen));
  const fill = (d: string, col: string, o = 1) => `<path d="${d}" fill="${col}" fill-opacity="${o}"/>`;
  const stroke = (d: string, col: string, w: number, o = 1) =>
    `<path d="${d}" fill="none" stroke="${col}" stroke-width="${w}" stroke-opacity="${o}" stroke-linecap="round"/>`;
  const parts: string[] = [];
  let text = "";
  const stLine = (x: number, y: number, anchor: string, col: string) =>
    `<text x="${x}" y="${y}" font-size="4.6" fill="${col}" fill-opacity=".8" text-anchor="${anchor}"><tspan font-weight="300">FM ${st.fs}</tspan> <tspan font-weight="500">${esc(st.n)}</tspan></text>`;
  if (tpl === "freq") {
    const ty = 54 + R() * 10,
      step = R() < 0.5 ? 2.2 : 3;
    let ticks = "";
    for (let i = 0, x = 6; x <= 94; x += step, i++) ticks += "M" + r2(x) + " " + r2(ty + (i % 5 === 0 ? -3 : 0)) + "V" + r2(ty + 3);
    const fx = 6 + ((st.f - 87) / 21) * 88,
      size = Math.min(15, 80 / longest);
    parts.push(stroke(ticks, c.p1, 0.45, 0.75), stroke("M" + r2(fx) + " " + r2(ty - 7) + "V" + r2(ty + 5), c.p2, 1.1) + fill(circ(fx, ty - 8, 1.5), c.p2));
    parts.push(`<text x="3" y="104" font-size="33" font-weight="200" fill="${c.p1}" style="letter-spacing:-0.05em">${st.fs}</text>`);
    text =
      textBlock(lines, 7, 7 + size * 0.9, size, 1.15, onC(c.bg)) +
      `<text x="7" y="${r2(Math.max(ty - 11, 12 + L * size * 1.15))}" font-size="4.6" font-weight="500" fill="${onC(c.bg)}" fill-opacity=".8">${esc(st.n)}</text>`;
  } else if (tpl === "split") {
    const split = 52 + R() * 14,
      size = Math.min(15, 86 / longest),
      cy = split + 14 + R() * 16;
    parts.push(fill(box(0, 0, 100, split), c.p1), fill(circ(72 + R() * 16, cy, 5 + R() * 4), c.p2));
    let rules = "";
    for (let i = 0; i < 3; i++) rules += box(7, split + 15 + i * 5, 40 - i * 9, 0.35);
    parts.push(fill(rules, onC(c.bg), 0.28));
    text = textBlock(lines, 7, split - 4 - (L - 1) * size * 1.12, size, 1.12, onC(c.p1)) + stLine(7, r2(split + 9), "start", onC(c.bg));
  } else if (tpl === "horizon") {
    const hy = 56 + R() * 14,
      r = 10 + R() * 8,
      cx = 76 + R() * 10,
      cy = hy + r * 0.15,
      size = Math.min(14, 56 / longest);
    let stars = "";
    if (lum(c.bg) < 0.12) for (let i = 0; i < 26; i++) stars += circ(R() * 100, R() * (hy - 14), 0.25 + R() * 0.35);
    let refl = "";
    for (let i = 0; i < 5; i++) {
      const w = r * 1.7 * (1 - i * 0.14);
      refl += box(cx - w / 2, hy + 3 + i * 5.5, w, Math.max(0.3, 1.1 - i * 0.15));
    }
    parts.push(
      fill(stars, c.ink, 0.55),
      fill(circ(cx, cy, r * 1.9), c.p1, 0.2) + fill(circ(cx, cy, r * 1.4), c.p1, 0.32),
      fill(circ(cx, cy, r), c.p2) + fill(box(0, hy, 100, 100 - hy), c.bg),
      fill(refl, c.p2, 0.45) + fill(box(0, hy - 0.2, 100, 0.4), c.p1, 0.7),
    );
    text = textBlock(lines, 7, hy - 3 - (L - 1) * size * 1.15, size, 1.15, onC(c.bg)) + stLine(7, r2(hy + 9), "start", onC(c.bg));
  } else if (tpl === "label") {
    const cx = 44 + R() * 12,
      cy = 44 + R() * 12,
      lr = 28 + R() * 5;
    let g = "";
    for (let rr = lr + 2; rr < 56; rr += 1.9) g += circ(cx, cy, rr);
    const ri = lr + 6 + R() * 10,
      a0 = R() * 6.28,
      a1 = a0 + 1 + R();
    const arc = "M" + r2(cx + ri * Math.cos(a0)) + " " + r2(cy + ri * Math.sin(a0)) + "A" + r2(ri) + " " + r2(ri) + " 0 0 1 " + r2(cx + ri * Math.cos(a1)) + " " + r2(cy + ri * Math.sin(a1));
    const size = Math.min(10.5, (lr * 1.5) / longest);
    parts.push(stroke(g, c.p1, 0.35, 0.6), stroke(arc, c.p1, 1.1), fill(circ(cx, cy, lr), c.p2));
    text = textBlock(lines, cx, cy - ((L - 1) * size * 1.2) / 2 + size * 0.35, size, 1.2, onC(c.p2), "middle", 900) + stLine(95, 96, "end", onC(c.bg));
  } else {
    const k = Math.floor(R() * 2),
      cx = [72 + R() * 10, 24 + R() * 12][k],
      cy = [72 + R() * 10, 76 + R() * 8][k];
    const size = Math.min(13.5, 64 / longest),
      zoneY = 7 + L * size * 1.15 + 9,
      ph = R() * 6.28;
    let ls = "",
      inner = "";
    for (let j = 1; j <= 12; j++) {
      const base = j * 6.6;
      let seg = "",
        on = false;
      for (let q = 0; q <= 72; q++) {
        const tt = (q / 72) * Math.PI * 2,
          rr = base * (1 + 0.12 * Math.sin(3 * tt + ph + j * 0.2));
        const x = cx + rr * Math.cos(tt),
          y = cy + rr * Math.sin(tt);
        if (x < 74 && y < zoneY) {
          on = false;
          continue;
        }
        seg += (on ? "L" : "M") + r2(x) + " " + r2(y);
        on = true;
      }
      if (j === 1) inner = seg + "Z";
      else ls += seg;
    }
    parts.push(stroke(ls, c.p1, 0.5), fill(inner, c.p2));
    text = textBlock(lines, 7, 7 + size * 0.9, size, 1.15, onC(c.bg)) + stLine(7, r2(7 + L * size * 1.15 + 4), "start", onC(c.bg));
  }
  return { bg: c.bg, parts, text: `<g style="font-family:${SANS.replace(/"/g, "'")}">${text}</g>`, c };
}
