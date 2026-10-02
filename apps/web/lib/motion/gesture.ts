// Gesture maths shared by every drag (MOTION.md §3).

export const VELOCITY_WINDOW_MS = 80;
export const RUBBER_LIMIT = 80;
export const DISMISS_DISTANCE_RATIO = 0.25;
export const DISMISS_VELOCITY = 0.5; // px/ms

/** Velocity over the last 80ms of pointer samples (not just the last two frames). */
export class VelocityTracker {
  private samples: Array<{ t: number; p: number }> = [];

  constructor(private readonly windowMs = VELOCITY_WINDOW_MS) {}

  reset(t: number, p: number): void {
    this.samples = [{ t, p }];
  }

  add(t: number, p: number): void {
    this.samples.push({ t, p });
    // Keep a bounded history; one sample older than the window is kept as a
    // reference point when the window itself holds a single sample.
    while (this.samples.length > 2 && t - this.samples[1].t > this.windowMs) this.samples.shift();
  }

  /** px per ms at time `now`; 0 if the pointer rested for longer than the window. */
  velocity(now: number): number {
    const last = this.samples[this.samples.length - 1];
    if (!last || this.samples.length < 2 || now - last.t > this.windowMs) return 0;
    const inWindow = this.samples.filter((sample) => last.t - sample.t <= this.windowMs);
    const first = inWindow.length >= 2 ? inWindow[0] : this.samples[this.samples.length - 2];
    const dt = last.t - first.t;
    return dt > 0 ? (last.p - first.p) / dt : 0;
  }
}

/** Damped overscroll: offset = limit · (1 − 1 / (d · 0.55 / limit + 1)). */
export function rubberBand(distance: number, limit = RUBBER_LIMIT): number {
  if (distance <= 0) return 0;
  return limit * (1 - 1 / ((distance * 0.55) / limit + 1));
}

/** Drag offset for a dismissable sheet: 1:1 downwards, damped upwards. */
export function sheetDragOffset(rawDy: number, limit = RUBBER_LIMIT): number {
  return rawDy >= 0 ? rawDy : -rubberBand(-rawDy, limit);
}

/** Close when dragged past 25% of the height, or flung down faster than 0.5 px/ms. */
export function shouldDismiss(offset: number, height: number, velocity: number): boolean {
  if (velocity > DISMISS_VELOCITY) return true;
  if (velocity < -DISMISS_VELOCITY) return false;
  return height > 0 && offset > height * DISMISS_DISTANCE_RATIO;
}

/** Backdrop opacity falls linearly with the drag distance. */
export function scrimOpacityForOffset(offset: number, height: number, max = 1): number {
  if (height <= 0) return max;
  return Math.max(0, Math.min(max, max * (1 - offset / height)));
}
