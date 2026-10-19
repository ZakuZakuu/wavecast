import { describe, expect, it } from "vitest";

import { bareCoverSvg } from "../lib/cover/build-cover";
import { coverSvg, composeCover, COVER_MOTIFS, COVER_STYLES } from "../lib/cover/styled";
import { LAYOUT_COUNTS } from "../lib/cover/styled/styles";
import { coverViewToSvg } from "../lib/cover/styled/svg";

const STYLED = COVER_STYLES.filter((style) => style !== "legacy");
const params = { stationId: "night" as const, seed: 7, heading: "夜航" };

describe("cover as a standalone svg", () => {
  it("is well-formed for every style, layout and picture, with no CSS units or holes left in it", () => {
    const parser = new DOMParser();
    let count = 0;
    for (const style of STYLED) {
      for (let layout = 0; layout < LAYOUT_COUNTS[style]; layout += 1) {
        for (const motif of COVER_MOTIFS) {
          const svg = coverSvg({ ...params, seed: count, pin: { style, motif, layout } }, 128);
          count += 1;
          expect(svg, `${style}/${layout}/${motif}`).not.toMatch(/cqw|NaN|undefined|Infinity/);
          const doc = parser.parseFromString(svg, "image/svg+xml");
          expect(doc.querySelector("parsererror"), `${style}/${layout}/${motif}`).toBeNull();
          expect(doc.documentElement.getAttribute("width")).toBe("128");
        }
      }
    }
    expect(count).toBe(900);
  });

  it("carries a layer's blur, blend, clip, mask and glow across", () => {
    const find = (style: (typeof STYLED)[number], pattern: RegExp) => {
      for (let seed = 0; seed < 40; seed += 1) {
        for (const motif of COVER_MOTIFS) {
          for (let layout = 0; layout < LAYOUT_COUNTS[style]; layout += 1) {
            if (pattern.test(coverSvg({ ...params, seed, pin: { style, motif, layout } }))) return true;
          }
        }
      }
      return false;
    };
    expect(find("glow", /feGaussianBlur/)).toBe(true);
    expect(find("glow", /radialGradient id="l\d+f"/)).toBe(true);
    expect(find("neon", /feDropShadow/)).toBe(true);
    expect(find("neon", /<pattern id="l\d+g"/)).toBe(true);
    expect(find("riso", /mix-blend-mode:multiply/)).toBe(true);
    expect(find("poster", /<clipPath/)).toBe(true);
    expect(find("sleeve", /mask-type:alpha/)).toBe(true);
  });

  it("is the same cover every time, leaves out text and grain, and fades gradients without grey", () => {
    const composed = composeCover({ ...params, bare: true });
    if (composed.kind !== "styled") throw new Error("expected a styled cover");
    const svg = coverViewToSvg(composed.view);
    expect(coverViewToSvg(composed.view)).toBe(svg);
    expect(svg).not.toMatch(/<text|feTurbulence/);
    expect(coverSvg({ ...params, pin: { style: "glow", motif: "moon", layout: 0 } })).toMatch(/stop-opacity="0"/);
  });

  it("falls back to the original generator's bare svg for an original cover", () => {
    for (let seed = 0; seed < 500; seed += 1) {
      const original = { ...params, seed };
      if (composeCover(original).kind === "legacy") {
        expect(coverSvg(original, 200)).toBe(bareCoverSvg(original, 200));
        return;
      }
    }
    throw new Error("no original cover in 500 seeds");
  });
});
