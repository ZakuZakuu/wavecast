// Shared poster toolkit, bundled to dist/wc.js and exposed as window.WC.
// Covers come from the product's own generator so the poster shows real WaveCast covers.
import { buildCover, type CoverBox } from "../../../../apps/web/lib/cover/build-cover";
import { STATIONS, type StationId } from "../../../../apps/web/lib/stations";
import { logoMarkSvg } from "../../../../apps/web/lib/brand/logo-mark";
// @ts-ignore - plain JS module without types
import qrcode from "qrcode-generator";

const cq = (v: number | null) => (v === null ? "auto" : `${v}cqw`);
const place = (b: CoverBox) =>
  `position:absolute;left:${cq(b.left)};right:${cq(b.right)};top:${cq(b.top)};bottom:${cq(b.bottom)};${b.width === null ? "" : `width:${cq(b.width)};`}`;

/** HTML of a cover, a port of components/cover/type-cover.tsx (container-query units). */
export function coverHtml(stationId: StationId, seed: number, heading: string, bare = false): string {
  const c = buildCover({ stationId, seed, heading, bare });
  const { title, stationLine, number } = c;
  const paths = c.slots
    .map((s) => `<path d="${s.d}" fill="${s.fill}" fill-opacity="${s.o}" stroke="${s.stroke}" stroke-width="${s.sw}" stroke-opacity="${s.so}" stroke-linecap="round" stroke-linejoin="round"/>`)
    .join("");
  const num = number
    ? `<span style="${place(number)}font-family:var(--num);font-size:34cqw;font-weight:200;line-height:1;letter-spacing:-.05em;color:${number.color}">${c.freq}</span>`
    : "";
  const text = bare
    ? ""
    : `<span style="${place(title)}font-family:${title.serif ? "var(--serif)" : "inherit"};font-size:${cq(title.size)};font-weight:${title.weight};line-height:${title.lh};letter-spacing:${title.ls};text-align:${title.align};${title.vertical ? "writing-mode:vertical-rl;" : ""}white-space:pre-line;color:${title.color}">${c.heading}</span>` +
      `<span style="${place(stationLine)}font-size:4.6cqw;line-height:1.3;text-align:${stationLine.align};white-space:nowrap;color:${stationLine.color};opacity:.78">${stationLine.freqText ? `<span style="font-weight:300">${stationLine.freqText}${c.freq} </span>` : ""}<span style="font-weight:500">${c.station}</span></span>`;
  return `<div class="cover" style="width:100%;aspect-ratio:1/1;position:relative;overflow:hidden;container-type:inline-size;background:${c.bg}"><svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice" style="position:absolute;inset:0;width:100%;height:100%;display:block">${paths}</svg>${num}${text}</div>`;
}

/** Fill every <div data-cover="station,seed,heading"> with a cover. */
export function mountCovers(root: ParentNode = document) {
  root.querySelectorAll<HTMLElement>("[data-cover]").forEach((el) => {
    const [st, seed, ...h] = el.dataset.cover!.split("|");
    el.innerHTML = coverHtml(st as StationId, Number(seed), h.join("|").replace(/\\n/g, "\n"), el.dataset.bare === "1");
  });
}

export function rng(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function qrPath(text: string, cell = 1): { d: string; size: number } {
  const q = qrcode(0, "M");
  q.addData(text);
  q.make();
  const n = q.getModuleCount();
  let d = "";
  for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) if (q.isDark(r, c)) d += `M${c * cell} ${r * cell}h${cell}v${cell}h${-cell}z`;
  return { d, size: n * cell };
}

export const logo = (dark = false) => logoMarkSvg({ dark });

(window as any).WC = { coverHtml, mountCovers, rng, qrPath, logo, STATIONS };
