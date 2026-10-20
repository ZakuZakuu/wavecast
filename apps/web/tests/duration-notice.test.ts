import { describe, expect, it } from "vitest";
import { durationNoticeText } from "../lib/duration-notice";

describe("durationNoticeText", () => {
  it("keeps old API responses and programmes without a shortfall quiet", () => {
    expect(durationNoticeText(undefined)).toBeNull();
    expect(durationNoticeText(null)).toBeNull();
  });

  it("shows actual and requested minutes without inventing a reason", () => {
    expect(durationNoticeText({ target_seconds: 2100, actual_seconds: 825 }))
      .toBe("实际约 14 分钟，未达到目标约 35 分钟。");
  });
});
