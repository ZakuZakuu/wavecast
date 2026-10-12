import { getInfo as sansInfo, loadFont as loadSans } from "@remotion/google-fonts/NotoSansSC";
import { getInfo as serifInfo, loadFont as loadSerif } from "@remotion/google-fonts/NotoSerifSC";
import { content } from "../content";

// The render machine is Linux (no PingFang): Noto Sans SC for UI and
// captions, Noto Serif SC for cover titles. A CJK Google font is split into
// ~100 unicode-range chunks per weight, so only the chunks that contain a
// character of the film's text are loaded (derived from content.ts, so new
// copy is covered automatically), plus Latin.

const TEXT = JSON.stringify(content) + "FM 0123456789.:：，、《》›";

function parseRange(range: string): Array<[number, number]> {
  return range.split(",").map((part) => {
    const [a, b] = part.trim().replace(/^U\+/i, "").split("-");
    return [parseInt(a, 16), parseInt(b ?? a, 16)];
  });
}

function subsetsFor(ranges: Record<string, string>): string[] {
  const codes = new Set(Array.from(TEXT, (ch) => ch.codePointAt(0)!));
  return Object.entries(ranges)
    .filter(([name, range]) => name === "latin" || parseRange(range).some(([lo, hi]) => [...codes].some((c) => c >= lo && c <= hi)))
    .map(([name]) => name);
}

const sans = loadSans("normal", {
  weights: ["200", "300", "400", "500", "600", "700", "900"],
  subsets: subsetsFor(sansInfo().unicodeRanges) as never,
  ignoreTooManyRequestsWarning: true,
});
const serif = loadSerif("normal", {
  weights: ["700", "900"],
  subsets: subsetsFor(serifInfo().unicodeRanges) as never,
  ignoreTooManyRequestsWarning: true,
});

export const SANS = `"${sans.fontFamily}", sans-serif`;
export const SERIF = `"${serif.fontFamily}", serif`;
