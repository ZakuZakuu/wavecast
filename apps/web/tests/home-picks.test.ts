import { describe, expect, it } from "vitest";

import { dedupeByTitle, pickMeta, RECOMMENDATION_MINUTES } from "../lib/home-picks";

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
