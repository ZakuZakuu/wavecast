import { describe, expect, it } from "vitest";
import { sourceNoticeText } from "../lib/source-notice";

describe("sourceNoticeText", () => {
  it("is silent without a notice or without artists", () => {
    expect(sourceNoticeText(undefined)).toBeNull();
    expect(sourceNoticeText(null)).toBeNull();
    expect(sourceNoticeText({ kind: "UNPLAYABLE_ARTISTS", artists: [] })).toBeNull();
    expect(sourceNoticeText({ kind: "UNPLAYABLE_ARTISTS", artists: ["  "] })).toBeNull();
  });

  it("names the artists without claiming a reason", () => {
    const text = sourceNoticeText({ kind: "UNPLAYABLE_ARTISTS", artists: ["椎名林檎", "Mogwai"] });
    expect(text).toBe("暂时没有找到 椎名林檎、Mogwai 可以播放的音源，已为你搭配相近的曲目。");
    expect(text).not.toContain("版权");
  });
});
