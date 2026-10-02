import { describe, expect, it } from "vitest";

import { cubicBezier, easeEnter, easeExit, easeStandard } from "../lib/motion/easing";
import {
  rubberBand,
  scrimOpacityForOffset,
  sheetDragOffset,
  shouldDismiss,
  VelocityTracker,
} from "../lib/motion/gesture";
import { SPRING, springAtRest, springSettleMs, springStep } from "../lib/motion/spring";

describe("spring", () => {
  it("uses stiffness 380, damping 36, mass 1 and settles in about 350–450ms", () => {
    expect(SPRING).toEqual({ stiffness: 380, damping: 36, mass: 1 });
    const ms = springSettleMs(0, 300);
    expect(ms).toBeGreaterThan(250);
    expect(ms).toBeLessThan(500);
  });

  it("barely overshoots", () => {
    let state = { position: 0, velocity: 0 };
    let max = 0;
    for (let t = 0; t < 1500; t += 16) {
      state = springStep(state, 100, 16);
      max = Math.max(max, state.position);
    }
    expect(max).toBeLessThan(102);
    expect(springAtRest(state, 100)).toBe(true);
  });

  it("carries the release velocity", () => {
    const slow = springStep({ position: 0, velocity: 0 }, 0, 50);
    const flung = springStep({ position: 0, velocity: 2 }, 0, 50);
    expect(slow.position).toBe(0);
    expect(flung.position).toBeGreaterThan(20);
  });

  it("is frame-rate independent", () => {
    let a = { position: 0, velocity: 0 };
    for (let i = 0; i < 12; i += 1) a = springStep(a, 100, 16);
    const b = springStep({ position: 0, velocity: 0 }, 100, 192);
    expect(a.position).toBeCloseTo(b.position, 0);
  });
});

describe("velocity", () => {
  it("averages the last 80ms instead of the last two frames", () => {
    const tracker = new VelocityTracker();
    tracker.reset(0, 0);
    for (let t = 16; t <= 160; t += 16) tracker.add(t, t * 1); // 1 px/ms
    tracker.add(168, 160 + 40); // a noisy last frame
    const v = tracker.velocity(168);
    expect(v).toBeGreaterThan(1);
    expect(v).toBeLessThan(2); // two-frame estimate would be 5 px/ms
  });

  it("is zero when the finger rested before release", () => {
    const tracker = new VelocityTracker();
    tracker.reset(0, 0);
    tracker.add(16, 30);
    expect(tracker.velocity(200)).toBe(0);
    expect(new VelocityTracker().velocity(0)).toBe(0);
  });
});

describe("damping and dismissal", () => {
  it("applies the rubber band formula with limit 80", () => {
    expect(rubberBand(0)).toBe(0);
    expect(rubberBand(80)).toBeCloseTo(80 * (1 - 1 / 1.55));
    expect(rubberBand(10_000)).toBeLessThan(80);
    expect(sheetDragOffset(40)).toBe(40);
    expect(sheetDragOffset(-80)).toBeCloseTo(-rubberBand(80));
  });

  it("dismisses past 25% of the height or on a fast downward fling", () => {
    expect(shouldDismiss(200, 800, 0)).toBe(false);
    expect(shouldDismiss(201, 800, 0)).toBe(true);
    expect(shouldDismiss(20, 800, 0.6)).toBe(true);
    expect(shouldDismiss(300, 800, -0.6)).toBe(false);
  });

  it("fades the scrim linearly with the drag", () => {
    expect(scrimOpacityForOffset(0, 600)).toBe(1);
    expect(scrimOpacityForOffset(300, 600)).toBe(0.5);
    expect(scrimOpacityForOffset(900, 600)).toBe(0);
    expect(scrimOpacityForOffset(300, 600, 0.3)).toBeCloseTo(0.15);
  });
});

describe("easing", () => {
  it("matches the CSS cubic-bezier endpoints and shape", () => {
    for (const ease of [easeStandard, easeEnter, easeExit]) {
      expect(ease(0)).toBe(0);
      expect(ease(1)).toBe(1);
    }
    expect(easeEnter(0.3)).toBeGreaterThan(0.6); // fast in
    expect(easeExit(0.3)).toBeLessThan(0.15); // slow start
    expect(cubicBezier(0, 0, 1, 1)(0.37)).toBeCloseTo(0.37, 3);
  });
});
