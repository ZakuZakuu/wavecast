import { describe, expect, it } from "vitest";
import { browserGuidance } from "../lib/browser-guidance";

describe("browser handoff guidance", () => {
  it("detects WeChat before the normal browser or desktop cases", () => {
    expect(browserGuidance("Mozilla/5.0 (iPhone) AppleWebKit Mobile MicroMessenger/8.0")).toBe("wechat-ios");
    expect(browserGuidance("Mozilla/5.0 (Linux; Android 14) Chrome/120 Mobile MicroMessenger/8.0")).toBe("wechat-other");
    expect(browserGuidance("Mozilla/5.0 (Windows NT 10.0) MicroMessenger/4.0")).toBe("wechat-other");
  });
  it("recognises iPad desktop UA without nudging normal mobile browsers", () => {
    expect(browserGuidance("Mozilla/5.0 (Macintosh) Safari/605 MicroMessenger/8.0", 5)).toBe("wechat-ios");
    expect(browserGuidance("Mozilla/5.0 (Macintosh) Safari/605", 5)).toBe("none");
    expect(browserGuidance("Mozilla/5.0 (iPhone) Safari/605")).toBe("none");
    expect(browserGuidance("Mozilla/5.0 (Linux; Android 14) Chrome/120 Mobile")).toBe("none");
  });
  it("offers a hint for desktop browsers", () => {
    expect(browserGuidance("Mozilla/5.0 (Windows NT 10.0) Chrome/120")).toBe("desktop");
    expect(browserGuidance("Mozilla/5.0 (Macintosh) Safari/605", 0)).toBe("desktop");
  });
});
