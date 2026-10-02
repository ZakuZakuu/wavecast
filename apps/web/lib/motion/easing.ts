// Cubic-bezier curves matching the CSS tokens (MOTION.md §2) and a rAF tween.
import type { Cancel } from "./spring";

export type Easing = (t: number) => number;

/** CSS cubic-bezier(x1, y1, x2, y2) as a JS easing function. */
export function cubicBezier(x1: number, y1: number, x2: number, y2: number): Easing {
  const cx = 3 * x1;
  const bx = 3 * (x2 - x1) - cx;
  const ax = 1 - cx - bx;
  const cy = 3 * y1;
  const by = 3 * (y2 - y1) - cy;
  const ay = 1 - cy - by;
  const sampleX = (t: number) => ((ax * t + bx) * t + cx) * t;
  const sampleY = (t: number) => ((ay * t + by) * t + cy) * t;
  const slopeX = (t: number) => (3 * ax * t + 2 * bx) * t + cx;
  const solveT = (x: number) => {
    let t = x;
    for (let i = 0; i < 8; i += 1) {
      const error = sampleX(t) - x;
      if (Math.abs(error) < 1e-6) return t;
      const slope = slopeX(t);
      if (Math.abs(slope) < 1e-6) break;
      t -= error / slope;
    }
    // Bisection fallback.
    let lo = 0;
    let hi = 1;
    t = x;
    for (let i = 0; i < 30; i += 1) {
      const value = sampleX(t);
      if (Math.abs(value - x) < 1e-6) break;
      if (value < x) lo = t;
      else hi = t;
      t = (lo + hi) / 2;
    }
    return t;
  };
  return (t: number) => {
    if (t <= 0) return 0;
    if (t >= 1) return 1;
    return sampleY(solveT(t));
  };
}

export const easeStandard = cubicBezier(0.2, 0.8, 0.2, 1);
export const easeEnter = cubicBezier(0.05, 0.7, 0.1, 1);
export const easeExit = cubicBezier(0.3, 0, 0.8, 0.15);
export const linear: Easing = (t) => t;

export const DUR = { instant: 100, fast: 150, base: 250, slow: 350, page: 400 } as const;

/** Time-based tween on requestAnimationFrame; cancellable mid-flight. */
export function tween(options: {
  from: number;
  to: number;
  duration: number;
  easing?: Easing;
  onUpdate: (value: number, progress: number) => void;
  onComplete?: () => void;
}): Cancel {
  const easing = options.easing ?? easeStandard;
  const start = performance.now();
  if (options.duration <= 0) {
    options.onUpdate(options.to, 1);
    options.onComplete?.();
    return () => undefined;
  }
  let frame = requestAnimationFrame(function tick(now) {
    const progress = Math.min(1, (now - start) / options.duration);
    const eased = easing(progress);
    options.onUpdate(options.from + (options.to - options.from) * eased, progress);
    if (progress < 1) frame = requestAnimationFrame(tick);
    else options.onComplete?.();
  });
  return () => cancelAnimationFrame(frame);
}

export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined"
    && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;
}
