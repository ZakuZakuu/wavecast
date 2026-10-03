import { describe, expect, it } from "vitest";

import {
  buildCover,
  contrastRatio,
  coverSetup,
  longestLine,
  MIN_TITLE_CONTRAST,
  textOn,
  visualLength,
  type CoverParams,
} from "../lib/cover/build-cover";
import { breakHeading, coverHeading, programmeCover, seedFromId } from "../lib/cover/programme-cover";
import { STATIONS, type CoverTemplate, type StationId } from "../lib/stations";

/** First seed whose cover uses `template` on `station`. */
function seedFor(stationId: StationId, template: CoverTemplate): number {
  for (let seed = 0; seed < 5000; seed += 1) if (coverSetup(stationId, seed).template === template) return seed;
  throw new Error(`no seed for ${stationId}/${template}`);
}

const cover = (stationId: StationId, template: CoverTemplate, heading: string, extra: Partial<CoverParams> = {}) =>
  buildCover({ stationId, seed: seedFor(stationId, template), heading, ...extra });

describe("cover title sizing", () => {
  it("counts CJK as 1 and latin as 0.56 visual width", () => {
    expect(visualLength("方大同")).toBe(3);
    expect(visualLength("UK")).toBeCloseTo(1.12);
    expect(longestLine("UK Garage\n怎么来的")).toBeCloseTo(9 * 0.56);
  });

  it("scales the title by the longest line and caps it per template", () => {
    expect(cover("casual", "freq", "专注两小时工作").title.size).toBeCloseTo(80 / 7, 2);
    expect(cover("casual", "freq", "夜里").title.size).toBe(15);
    expect(cover("night", "horizon", "一二三四五六七").title.size).toBe(8);
    expect(cover("lineage", "contour", "一二三四五六").title.size).toBeCloseTo(64 / 6, 2);
    const split = cover("crate", "split", "一二三四五六七八");
    expect(split.title.size).toBeCloseTo(86 / 8, 2);
  });

  it("fits the vertical column title inside the column", () => {
    const column = cover("portrait", "column", "坂本龙一\n这些年");
    expect(column.title.vertical).toBe(true);
    expect(column.title.serif).toBe(true);
    expect(column.title.size).toBeLessThanOrEqual(14.5);
  });
});

describe("cover v2 generator", () => {
  it("is deterministic and varies with the seed", () => {
    const a = buildCover({ stationId: "night", seed: 11, heading: "夜航\n低音线" });
    expect(buildCover({ stationId: "night", seed: 11, heading: "夜航\n低音线" })).toEqual(a);
    const others = [12, 13, 14, 15].map((seed) => buildCover({ stationId: "night", seed, heading: "夜航\n低音线" }));
    expect(others.some((other) => other.bg !== a.bg || other.slots[0].d !== a.slots[0].d)).toBe(true);
  });

  it("only uses each station's three templates, and all of them", () => {
    for (const station of STATIONS) {
      const seen = new Set<CoverTemplate>();
      for (let seed = 0; seed < 300; seed += 1) seen.add(coverSetup(station.id, seed).template);
      expect([...seen].sort()).toEqual([...station.templates].sort());
    }
  });

  it("produces dark, light and vivid palettes, with the station's dark odds", () => {
    for (const station of STATIONS) {
      const modes = { dark: 0, light: 0, vivid: 0 };
      const n = 2000;
      for (let seed = 0; seed < n; seed += 1) modes[coverSetup(station.id, seed).palette.mode] += 1;
      expect(modes.dark / n).toBeCloseTo(station.cover.dark, 1);
      expect(modes.light).toBeGreaterThan(0);
      expect(modes.vivid).toBeGreaterThan(0);
    }
  });

  it("keeps contour lines out of the title zone", () => {
    const c = cover("lineage", "contour", "x");
    const zoneY = 7 + c.title.size * 1.15 + 9;
    const points = [...c.slots[0].d.matchAll(/[ML]([\d.-]+) ([\d.-]+)/g)].map((m) => [Number(m[1]), Number(m[2])]);
    expect(points.length).toBeGreaterThan(0);
    expect(points.every(([x, y]) => !(x < 74 && y < zoneY))).toBe(true);
  });

  it("varies composition within a template", () => {
    // horizon: sun left or right; split: band on top or bottom; column: left or right.
    const sides = (stationId: StationId, template: CoverTemplate, pick: (c: ReturnType<typeof buildCover>) => string) => {
      const seen = new Set<string>();
      for (let seed = 0; seed < 400; seed += 1) {
        const c = buildCover({ stationId, seed, heading: "测试" });
        if (c.template === template) seen.add(pick(c));
      }
      return seen;
    };
    expect(sides("night", "horizon", (c) => c.title.align)).toEqual(new Set(["left", "right"]));
    expect(sides("crate", "split", (c) => (c.title.top === null ? "top" : "bottom"))).toEqual(new Set(["top", "bottom"]));
    expect(sides("portrait", "column", (c) => (c.title.left !== null && c.title.left < 50 ? "left" : "right"))).toEqual(new Set(["left", "right"]));
  });

  it("always pads to eight slots; bare drops all text", () => {
    const c = cover("casual", "freq", "x");
    expect(c.slots).toHaveLength(8);
    expect(c.number).not.toBeNull();
    const bare = cover("casual", "freq", "x", { bare: true });
    expect(bare.bare).toBe(true);
    expect(bare.number).toBeNull();
    expect(bare.slots).toEqual(c.slots);
  });
});

describe("cover contrast", () => {
  it(`every palette surface that can carry a title reaches ${MIN_TITLE_CONTRAST}:1 for any seed`, () => {
    let worst = Infinity;
    for (const station of STATIONS) {
      for (let seed = 0; seed < 9973; seed += 1) {
        const { palette } = coverSetup(station.id, seed);
        for (const surface of [palette.bg, palette.p1, palette.p2]) {
          worst = Math.min(worst, contrastRatio(textOn(surface), surface));
        }
      }
    }
    expect(worst).toBeGreaterThanOrEqual(MIN_TITLE_CONTRAST);
  });

  it("the rendered title colour matches its surface", () => {
    for (const station of STATIONS) {
      for (let seed = 0; seed < 300; seed += 1) {
        const c = buildCover({ stationId: station.id, seed, heading: "测试标题" });
        expect(contrastRatio(c.title.color, c.title.on)).toBeGreaterThanOrEqual(MIN_TITLE_CONTRAST);
      }
    }
  });
});

describe("cover heading rule", () => {
  it("takes the part before a colon or comma", () => {
    expect(coverHeading("雨天开车：一些慢歌")).toBe("雨天开车");
    expect(coverHeading("方大同这些年, a story")).toBe("方大同\n这些年");
    expect(coverHeading("Lo-fi 从哪来")).toBe("Lo-fi\n从哪来");
    expect(coverHeading("Trip-hop：布里斯托的慢节拍")).toBe("Trip-hop");
    expect(coverHeading("雨天 - 开车")).toBe("雨天");
  });

  it("drops the heading when it is still wider than 10", () => {
    expect(coverHeading("从城市夜色里的律动出发听见爵士")).toBeNull();
    const c = programmeCover({ id: "x", title: "从城市夜色里的律动出发听见爵士", stationId: "portrait" });
    expect(c.params.bare).toBe(true);
    expect(c.titleBelow).toBe(true);
  });

  it("breaks once near the middle and never inside a latin word", () => {
    expect(breakHeading("睡前半小时")).toBe("睡前半小时");
    expect(breakHeading("UK Garage 怎么来的")).toBe("UK Garage\n怎么来的");
    expect(breakHeading("周五下班路上").split("\n")).toHaveLength(2);
  });
});

describe("programme cover params", () => {
  it("are stable for a programme id everywhere and follow the station", () => {
    const first = programmeCover({ id: "seed-1", title: "睡前半小时", stationId: "night" });
    expect(first).toEqual(programmeCover({ id: "seed-1", title: "睡前半小时", stationId: "night" }));
    expect(first.params.seed).toBe(seedFromId("seed-1"));
    expect(STATIONS.find((s) => s.id === "night")!.templates).toContain(first.template);
    // Bare (mini player / library) draws the same graphics as the full cover.
    expect(buildCover({ ...first.params, bare: true }).slots).toEqual(buildCover(first.params).slots);
  });

  it("gives a station's programmes visibly different covers", () => {
    const titles = ["夜航低音线", "雨夜慢频", "低速张力", "睡前半小时", "凌晨三点", "专注两小时", "海边夜色", "城市熄灯"];
    const covers = titles.map((title, index) => programmeCover({ id: `night-${index}-${title}`, title, stationId: "night" }));
    expect(new Set(covers.map((c) => c.template)).size).toBeGreaterThanOrEqual(2);
    expect(new Set(covers.map((c) => c.bg)).size).toBe(titles.length);
  });
});

describe("cover source alias", () => {
  it("a programme created from a card keeps the card's cover", async () => {
    const { rememberCoverSource, coverIdFor } = await import("../lib/cover/programme-cover");
    window.localStorage.clear();
    const card = programmeCover({ id: "featured-night-bedtime", title: "睡前半小时", stationId: "night" });
    rememberCoverSource("proposal-123", "featured-night-bedtime");
    expect(coverIdFor("proposal-123")).toBe("featured-night-bedtime");
    const player = programmeCover({ id: "proposal-123", title: "睡前半小时", stationId: "night" });
    expect(player.params.seed).toBe(card.params.seed);
    expect(player.bg).toBe(card.bg);
    expect(coverIdFor("other")).toBe("other");
  });
});
