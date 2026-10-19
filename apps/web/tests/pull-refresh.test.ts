import { describe, expect, it } from "vitest";

import { logoDrawState } from "../lib/brand/logo-line";
import { PULL_THRESHOLD, pullOffset, pullProgress } from "../lib/pull-refresh";

describe("pull offset", () => {
  it("follows the finger damped, and not at all for an upward drag", () => {
    expect(pullOffset(-30)).toBe(0);
    expect(pullOffset(0)).toBe(0);
    expect(pullOffset(100)).toBeCloseTo(55);
  });

  it("reaches the threshold at a comfortable drag and then softens", () => {
    const dyAtThreshold = PULL_THRESHOLD / 0.55;
    expect(pullOffset(dyAtThreshold)).toBeCloseTo(PULL_THRESHOLD);
    expect(pullOffset(dyAtThreshold + 100)).toBeGreaterThan(PULL_THRESHOLD);
    expect(pullOffset(dyAtThreshold + 100)).toBeLessThan(pullOffset(dyAtThreshold) + 55);
    expect(pullOffset(2000)).toBeLessThan(PULL_THRESHOLD + 28);
  });

  it("is monotonic", () => {
    let last = 0;
    for (let dy = 0; dy <= 600; dy += 10) {
      const offset = pullOffset(dy);
      expect(offset).toBeGreaterThanOrEqual(last);
      last = offset;
    }
  });

  it("draws the logo in proportion to the pull and completes at the threshold", () => {
    expect(pullProgress(0)).toBe(0);
    expect(pullProgress(PULL_THRESHOLD / 2)).toBeCloseTo(0.5);
    expect(pullProgress(PULL_THRESHOLD)).toBe(1);
    expect(pullProgress(PULL_THRESHOLD * 2)).toBe(1);
  });
});

describe("logo draw-on", () => {
  it("starts empty and finishes whole", () => {
    const start = logoDrawState(0);
    expect(start.tip).toBe(0);
    expect(start.antenna.visible).toBe(false);
    expect(start.body.visible).toBe(false);
    expect(start.dots.every((dot) => dot === 0)).toBe(true);

    const end = logoDrawState(1);
    expect(end.tip).toBeCloseTo(1);
    expect(end.window).toBeCloseTo(1);
    expect(end.knob).toBeCloseTo(1);
    expect(end.dots.every((dot) => Math.abs(dot - 1) < 1e-9)).toBe(true);
    for (const stroke of [end.antenna, end.body, end.needle]) expect(stroke).toEqual({ offset: 0, visible: true });
  });

  it("is a dot first (the antenna tip), then the antenna, the outline, and the details last", () => {
    const early = logoDrawState(0.06);
    expect(early.tip).toBeGreaterThan(0.5);
    expect(early.antenna.visible).toBe(false);
    expect(early.body.visible).toBe(false);
    const mid = logoDrawState(0.4);
    expect(mid.antenna.offset).toBe(0);
    expect(mid.body.visible).toBe(true);
    expect(mid.body.offset).toBeGreaterThan(0);
    expect(mid.knob).toBe(0);
  });

  it("clamps progress outside 0..1", () => {
    expect(logoDrawState(-1)).toEqual(logoDrawState(0));
    expect(logoDrawState(3)).toEqual(logoDrawState(1));
  });
});
