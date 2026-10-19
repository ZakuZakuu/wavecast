import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { TypeCover } from "../components/cover/type-cover";
import { rng } from "../lib/cover/build-cover";
import { cssToStyle } from "../lib/cover/styled/css";
import { composeCover } from "../lib/cover/styled";
import { MOTIFS } from "../lib/cover/styled/motifs";
import { COVER_MOTIFS, COVER_STYLES, type StyledCoverStyle } from "../lib/cover/styled/types";
import { MOTIF_POOLS, selectCover, STYLE_FAVOURITES } from "../lib/cover/styled/select";
import { nestedBlobRadii } from "../lib/cover/styled/shapes";
import { LAYOUT_COUNTS } from "../lib/cover/styled/styles";
import { emWidth, fitSize, splitTitle, titleBox } from "../lib/cover/styled/text";
import { STATIONS, type StationId } from "../lib/stations";

const STYLED = COVER_STYLES.filter((style): style is StyledCoverStyle => style !== "legacy");

describe("title layout", () => {
  it("keeps the editor's line breaks and splits a long single line near the middle", () => {
    expect(splitTitle("City Pop\n的来历")).toEqual(["City Pop", "的来历"]);
    expect(splitTitle("坂本龙一")).toEqual(["坂本龙一"]);
    expect(splitTitle("周五下班路上")).toEqual(["周五下班路上"]);
    expect(splitTitle("周五下班路上听点歌")).toEqual(["周五下班路", "上听点歌"]);
    expect(splitTitle("Bossa Nova 的来历")).toEqual(["Bossa", "Nova 的来历"]);
  });

  it("never leaves a latin hyphen word broken", () => {
    expect(splitTitle("Neo-Soul 入门").join("")).toBe("Neo-Soul入门");
    expect(splitTitle("Neo-Soul 入门")[0]).toBe("Neo-Soul");
  });

  it("sizes the title to the zone and to its longest line", () => {
    const zone = { w: 80, h: 30 };
    expect(fitSize(["坂本龙一"], zone, { max: 40, fw: 700 })).toBeCloseTo(((80 / 4) * 0.95), 1);
    expect(fitSize(["一"], zone, { max: 12, fw: 700 })).toBeCloseTo(12 * 0.95, 1);
    expect(fitSize(["坂本龙一", "龙"], { w: 80, h: 20 }, { max: 40, lh: 1, fw: 700 })).toBeCloseTo((20 / 2) * 0.95, 1);
    expect(fitSize(["坂本龙一"], zone, { max: 40, fw: 900 })).toBeLessThan(fitSize(["坂本龙一"], zone, { max: 40, fw: 700 }));
    expect(emWidth("Neo-Soul")).toBeGreaterThan(emWidth("neo"));
  });

  it("stacks a single CJK line one character per row, and turns other vertical text sideways", () => {
    const stacked = titleBox(["坂本龙一"], { x: 8, y: 8, w: 20, h: 72 }, { fam: "x", fw: 700, color: "#000", max: 19, vertical: true });
    expect(stacked.text).toBe("坂\n本\n龙\n一");
    expect(stacked.css).not.toContain("writing-mode");
    const sideways = titleBox(["Neo-Soul", "入门"], { x: 8, y: 8, w: 20, h: 72 }, { fam: "x", fw: 700, color: "#000", max: 19, vertical: true });
    expect(sideways.css).toContain("writing-mode:vertical-rl");
  });
});

describe("cover selection", () => {
  const draws = (stationId: StationId, n = 4000) => Array.from({ length: n }, (_, seed) => selectCover(stationId, seed));

  it("is deterministic and always inside the known styles, motifs and layouts", () => {
    for (const station of STATIONS) {
      for (const seed of [0, 1, 77, 9972]) {
        const choice = selectCover(station.id, seed);
        expect(selectCover(station.id, seed)).toEqual(choice);
        expect(COVER_STYLES).toContain(choice.style);
        expect(COVER_MOTIFS).toContain(choice.motif);
        const count = choice.style === "legacy" ? 1 : LAYOUT_COUNTS[choice.style];
        expect(choice.layout).toBeGreaterThanOrEqual(0);
        expect(choice.layout).toBeLessThan(count);
      }
    }
  });

  it("leans on each station's styles and pictures, keeps some of the original, and still varies", () => {
    for (const station of STATIONS) {
      const all = draws(station.id);
      const favourite = all.filter((choice) => (STYLE_FAVOURITES[station.id] as string[]).includes(choice.style)).length / all.length;
      expect(favourite).toBeGreaterThan(0.58);
      expect(favourite).toBeLessThan(0.78);
      const legacy = all.filter((choice) => choice.style === "legacy").length / all.length;
      expect(legacy).toBeGreaterThan(0.07);
      expect(legacy).toBeLessThan(0.13);
      const pooled = all.filter((choice) => MOTIF_POOLS[station.id].includes(choice.motif)).length / all.length;
      expect(pooled).toBeGreaterThan(0.85);
      expect(new Set(all.map((choice) => choice.style)).size).toBe(COVER_STYLES.length);
      expect(new Set(all.map((choice) => choice.motif)).size).toBe(COVER_MOTIFS.length);
    }
  });

  it("lets a pin override part or all of the choice", () => {
    const free = selectCover("night", 5);
    expect(selectCover("night", 5, { style: "riso", motif: "plant", layout: 3 })).toEqual({ style: "riso", motif: "plant", layout: 3 });
    expect(selectCover("night", 5, { style: "legacy" }).style).toBe("legacy");
    expect(selectCover("night", 5, { style: "neon" })).toMatchObject({ style: "neon", motif: free.motif });
  });

  it("only pools real motifs", () => {
    for (const pool of Object.values(MOTIF_POOLS)) for (const motif of pool) expect(COVER_MOTIFS).toContain(motif);
    expect(Object.keys(MOTIFS).sort()).toEqual([...COVER_MOTIFS].sort());
  });
});

describe("composed covers", () => {
  const heading = "City Pop\n的来历";

  it("draws something sound for every style, layout and picture", () => {
    for (const style of STYLED) {
      for (let layout = 0; layout < LAYOUT_COUNTS[style]; layout += 1) {
        for (const motif of COVER_MOTIFS) {
          const composed = composeCover({ stationId: "lineage", seed: 123, heading, pin: { style, motif, layout } });
          if (composed.kind !== "styled") throw new Error("pinned style should be styled");
          const { view } = composed;
          expect(view.layers.length).toBeGreaterThan(2);
          const text = JSON.stringify(view);
          expect(text).not.toMatch(/NaN|undefined|Infinity/);
          expect(view.bg).toMatch(/^#[0-9a-f]{6}$/);
          expect(view.title.text.split("\n").length).toBeLessThanOrEqual(3);
          expect(view.title.css).toMatch(/font-size:\d/);
        }
      }
    }
  });

  it("is deterministic, and the bare version draws the same picture without any words", () => {
    const pin = { style: "poster", motif: "keys", layout: 3 } as const;
    const full = composeCover({ stationId: "portrait", seed: 9, heading: "坂本龙一", pin });
    const again = composeCover({ stationId: "portrait", seed: 9, heading: "坂本龙一", pin });
    const bare = composeCover({ stationId: "portrait", seed: 9, heading: "坂本龙一", bare: true, pin });
    if (full.kind !== "styled" || bare.kind !== "styled") throw new Error("styled");
    expect(again).toEqual(full);
    expect(full.view.title.text).toBe("坂本龙一");
    expect(bare.view.title.text).toBe("");
    expect(bare.view.caption.text).toBe("");
    // Same palette and picture: the first (background) and the picture layers share their paths.
    expect(bare.view.layers[1].d).toBe(full.view.layers[1].d);
  });

  it("names the station and its frequency", () => {
    const composed = composeCover({ stationId: "night", seed: 4, heading: "睡前\n半小时", pin: { style: "neon", motif: "moon", layout: 0 } });
    if (composed.kind !== "styled") throw new Error("styled");
    expect(composed.view.caption.text).toBe("FM 105.8");
    expect(composed.view.caption2.text).toBe("夜里");
  });

  it("falls back to the original generator when the choice is the original", () => {
    expect(composeCover({ stationId: "casual", seed: 3, heading: "夜里", pin: { style: "legacy" } })).toEqual({ kind: "legacy" });
  });
});

describe("rendering", () => {
  it("turns CSS text into a React style, prefixes included", () => {
    expect(cssToStyle("left:6cqw;-webkit-mask-size:3cqw 3cqw;mix-blend-mode:multiply;")).toEqual({ left: "6cqw", WebkitMaskSize: "3cqw 3cqw", mixBlendMode: "multiply" });
    expect(cssToStyle("")).toEqual({});
  });

  it("renders a styled cover with its title, and the original cover through the same component", () => {
    const styled = renderToStaticMarkup(createElement(TypeCover, { params: { stationId: "lineage", seed: 4, heading: "City Pop\n的来历", pin: { style: "blue", motif: "skyline", layout: 3 } } }));
    expect(styled).toContain("FIG.");
    expect(styled).toContain("<path");
    expect(styled).toContain("wc-cover-grain");
    const small = renderToStaticMarkup(createElement(TypeCover, { params: { stationId: "lineage", seed: 4, heading: "City Pop\n的来历", bare: true, pin: { style: "blue", motif: "skyline", layout: 3 } } }));
    expect(small).not.toContain("wc-cover-grain");
    expect(small).not.toContain("FIG.");
    const legacy = renderToStaticMarkup(createElement(TypeCover, { params: { stationId: "casual", seed: 3, heading: "夜里", pin: { style: "legacy" } } }));
    expect(legacy).toContain("夜里");
    expect(legacy).not.toContain("wc-cover-grain");
  });
});

describe("contour lines", () => {
  it("never touch: every ring keeps a gap to the one inside it, for any seed", () => {
    const radii = [7, 12, 20, 28, 36, 44];
    for (let seed = 1; seed <= 300; seed += 1) {
      const rings = nestedBlobRadii(radii, rng(seed * 7919));
      expect(rings).toHaveLength(radii.length);
      for (let ring = 1; ring < rings.length; ring += 1) {
        rings[ring].forEach((value, step) => {
          expect(value - rings[ring - 1][step]).toBeGreaterThanOrEqual(3);
        });
      }
    }
  });

  it("are still wobbly rather than circles", () => {
    const rings = nestedBlobRadii([12, 20, 28], rng(5));
    const spread = Math.max(...rings[2]) - Math.min(...rings[2]);
    expect(spread).toBeGreaterThan(4);
  });
});
