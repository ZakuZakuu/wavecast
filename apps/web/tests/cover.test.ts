import { describe, expect, it } from "vitest";

import { buildCover, longestLine, visualLength } from "../lib/cover/build-cover";
import { breakHeading, coverHeading, programmeCover, seedFromId } from "../lib/cover/programme-cover";

const base = { seed: 3, bg: "#F1E9D8", p1: "#B0823A", p2: "#2E2A24", ink: "#2E2A24", station: "人物志", freq: "97.4" };

describe("cover title sizing", () => {
  it("counts CJK as 1 and latin as 0.56 visual width", () => {
    expect(visualLength("方大同")).toBe(3);
    expect(visualLength("UK")).toBeCloseTo(1.12);
    expect(longestLine("UK Garage\n怎么来的")).toBeCloseTo(9 * 0.56);
  });

  it("scales the title by the longest line and caps it per template", () => {
    // column: min(14.5, 64 / len)
    expect(buildCover({ ...base, template: "column", heading: "方大同\n这些年" }).titleSize).toBe(14.5);
    expect(buildCover({ ...base, template: "column", heading: "夜里的城市漫游" }).titleSize).toBeCloseTo(64 / 7, 2);
    // label: min(10.5, 46 / len)
    expect(buildCover({ ...base, template: "label", heading: "从方大同\n往外听" }).titleSize).toBe(10.5);
    expect(buildCover({ ...base, template: "label", heading: "一二三四五六" }).titleSize).toBeCloseTo(46 / 6, 2);
    // freq: min(15, 80 / len)
    expect(buildCover({ ...base, template: "freq", heading: "专注两小时工作" }).titleSize).toBeCloseTo(80 / 7, 2);
  });

  it("is deterministic for identical params and varies with the seed", () => {
    const a = buildCover({ ...base, template: "contour", heading: "UK Garage\n怎么来的" });
    const b = buildCover({ ...base, template: "contour", heading: "UK Garage\n怎么来的" });
    const c = buildCover({ ...base, seed: 4, template: "contour", heading: "UK Garage\n怎么来的" });
    expect(a).toEqual(b);
    expect(a.slots[0].d).not.toEqual(c.slots[0].d);
  });

  it("keeps contour lines out of the title zone", () => {
    const cover = buildCover({ ...base, template: "contour", heading: "x" });
    const points = [...cover.slots[0].d.matchAll(/[ML]([\d.-]+) ([\d.-]+)/g)].map((m) => [Number(m[1]), Number(m[2])]);
    expect(points.length).toBeGreaterThan(0);
    expect(points.every(([x, y]) => !(x < 74 && y < 46))).toBe(true);
  });

  it("always pads to six slots", () => {
    expect(buildCover({ ...base, template: "freq", heading: "x" }).slots).toHaveLength(6);
  });
});

describe("cover heading rule", () => {
  it("takes the part before a colon or comma", () => {
    expect(coverHeading("雨天开车：一些慢歌")).toBe("雨天开车");
    expect(coverHeading("方大同这些年, a story")).toBe("方大同\n这些年");
  });

  it("drops the heading when it is still wider than 10", () => {
    expect(coverHeading("从城市夜色里的律动出发听见爵士")).toBeNull();
    const cover = programmeCover({ id: "x", title: "从城市夜色里的律动出发听见爵士", stationId: "portrait" });
    expect(cover.params.bare).toBe(true);
    expect(cover.titleBelow).toBe(true);
  });

  it("breaks once near the middle and never inside a latin word", () => {
    expect(breakHeading("睡前半小时")).toBe("睡前半小时");
    expect(breakHeading("UK Garage 怎么来的")).toBe("UK Garage\n怎么来的");
    expect(breakHeading("周五下班路上").split("\n")).toHaveLength(2);
  });
});

describe("programme cover params", () => {
  it("are stable for a programme and follow the station's template", () => {
    const first = programmeCover({ id: "seed-1", title: "睡前半小时", stationId: "night" });
    expect(first).toEqual(programmeCover({ id: "seed-1", title: "睡前半小时", stationId: "night" }));
    expect(first.params.template).toBe("horizon");
    expect(first.params.seed).toBe(seedFromId("seed-1"));
    const casual = programmeCover({ id: "seed-2", title: "雨天开车", stationId: "casual" });
    expect(["freq", "split"]).toContain(casual.params.template);
  });
});
