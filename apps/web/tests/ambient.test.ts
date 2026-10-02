import { describe, expect, it } from "vitest";

import { approach, cleanTarget, smoothNoise, swingOffset, waveformY } from "../lib/motion/ambient";

describe("pointer swing", () => {
  it("is a decaying oscillation that settles to zero by 900ms", () => {
    const A = 1.2 * 38.75;
    expect(swingOffset(0, A)).toBe(0);
    expect(Math.abs(swingOffset(75, A))).toBeGreaterThan(Math.abs(swingOffset(375, A)));
    expect(swingOffset(900, A)).toBe(0);
    expect(swingOffset(2000, A)).toBe(0);
    // Changes sign (swings to both sides).
    expect(Math.sign(swingOffset(75, A))).not.toBe(Math.sign(swingOffset(225, A)));
  });
});

describe("waveform", () => {
  it("changes only slightly between consecutive frames", () => {
    for (const clean of [0, 0.4, 1]) {
      for (let x = 0; x <= 300; x += 30) {
        const a = waveformY(x, 1.0, clean);
        const b = waveformY(x, 1.0 + 1 / 60, clean);
        expect(Math.abs(a - b)).toBeLessThan(2.5);
      }
    }
  });

  it("is deterministic (no per-frame randomness)", () => {
    expect(smoothNoise(42, 3.3)).toBe(smoothNoise(42, 3.3));
    expect(waveformY(10, 0.5, 0.3)).toBe(waveformY(10, 0.5, 0.3));
  });

  it("mixes noise and sine by cleanliness", () => {
    // Fully clean is a pure sine of amplitude 12 around the midline.
    for (let x = 0; x <= 300; x += 7) expect(Math.abs(waveformY(x, 0.7, 1) - 28)).toBeLessThanOrEqual(12.0001);
    // Fully noisy contains no sine term: two times with the same noise phase differ only by noise.
    expect(cleanTarget(0)).toBe(0);
    expect(cleanTarget(1)).toBe(0.4);
    expect(cleanTarget(2)).toBe(0.75);
    expect(cleanTarget(3)).toBe(1);
  });
});

describe("approach", () => {
  it("moves about 6% per 60fps frame and is frame-rate independent", () => {
    expect(approach(0, 1, 1000 / 60)).toBeCloseTo(0.06);
    let at60 = 0;
    for (let i = 0; i < 6; i += 1) at60 = approach(at60, 1, 1000 / 60);
    let at30 = 0;
    for (let i = 0; i < 3; i += 1) at30 = approach(at30, 1, 1000 / 30);
    expect(at30).toBeCloseTo(at60, 6);
  });
});
