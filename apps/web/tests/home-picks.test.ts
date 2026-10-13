import { describe, expect, it } from "vitest";

import { dedupeByTitle, ideaStation, pickMeta, RECOMMENDATION_MINUTES } from "../lib/home-picks";

describe("home picks", () => {
  it("keeps only the first programme of each title", () => {
    const items = [
      { id: "a", title: "雨夜慢频" },
      { id: "b", title: "城市熄灯" },
      { id: "c", title: " 雨夜慢频 " },
      { id: "d", title: "City  Pop 之后" },
      { id: "e", title: "city pop 之后" },
    ];
    expect(dedupeByTitle(items).map((item) => item.id)).toEqual(["a", "b", "d"]);
  });

  it("formats the station and length line", () => {
    expect(pickMeta("夜里", 30)).toBe("夜里，约 30 分钟");
    expect(pickMeta("唱片行", null)).toBe("唱片行");
    expect(RECOMMENDATION_MINUTES).toBe(35);
  });
});

describe("ideaStation", () => {
  it("uses the station the backend chose when it is one we know", () => {
    expect(ideaStation({ station: "lineage" })).toBe("lineage");
    expect(ideaStation({ station: "night" })).toBe("night");
  });

  it("leaves older ideas, empty values and unknown stations to the keyword fallback", () => {
    expect(ideaStation({})).toBeUndefined();
    expect(ideaStation({ station: null })).toBeUndefined();
    expect(ideaStation({ station: "late-night-fm" })).toBeUndefined();
  });
});
