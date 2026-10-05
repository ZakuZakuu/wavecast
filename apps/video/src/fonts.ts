import { getInfo as sansInfo, loadFont as loadSans } from "@remotion/google-fonts/NotoSansSC";
import { getInfo as serifInfo, loadFont as loadSerif } from "@remotion/google-fonts/NotoSerifSC";
import { CHARSET } from "./charset.generated";

// Noto SC is split into ~100 unicode-range slices per weight. Loading only the
// slices that cover the film's text keeps a render to a few dozen requests.
function inRange(code: number, ranges: string) {
  return ranges.split(",").some((part) => {
    const [a, b] = part.trim().replace(/^U\+/i, "").split("-");
    const lo = parseInt(a, 16);
    const hi = b ? parseInt(b, 16) : lo;
    return code >= lo && code <= hi;
  });
}
function neededSubsets(ranges: Record<string, string>): string[] {
  const codes = [...(CHARSET + "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz .,:;!?'\"()-")].map((c) => c.codePointAt(0)!);
  return Object.entries(ranges)
    .filter(([, r]) => codes.some((c) => inRange(c, r)))
    .map(([name]) => name);
}

const sansSubsets = neededSubsets(sansInfo().unicodeRanges as Record<string, string>);
const serifSubsets = neededSubsets(serifInfo().unicodeRanges as Record<string, string>);

export const SANS = loadSans("normal", {
  weights: ["200", "300", "400", "500", "600", "700"],
  subsets: sansSubsets as never,
  ignoreTooManyRequestsWarning: true,
}).fontFamily;

export const SERIF = loadSerif("normal", {
  weights: ["900"],
  subsets: serifSubsets as never,
  ignoreTooManyRequestsWarning: true,
}).fontFamily;
