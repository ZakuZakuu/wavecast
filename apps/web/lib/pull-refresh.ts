// Pull-to-refresh maths for the home page (Frost-Home2): the content follows the finger damped,
// the logo is drawn while the pull grows, and a release past the threshold refreshes.
import { rubberBand } from "./motion/gesture";

/** Content offset (px) that counts as "ready to refresh". */
export const PULL_THRESHOLD = 72;
/** Where the content rests while a refresh runs; the logo stays visible above it. */
export const PULL_HOLD = 64;
/** A refresh shows the antenna swing for at least this long, however fast the answer is. */
export const PULL_MIN_REFRESH_MS = 800;
const PULL_DAMPING = 0.55;
const PULL_OVERSHOOT = 28;

/** Content offset for a finger drag of `dy` px: damped, and softer again past the threshold. */
export function pullOffset(dy: number): number {
  const damped = Math.max(0, dy) * PULL_DAMPING;
  return damped <= PULL_THRESHOLD ? damped : PULL_THRESHOLD + rubberBand(damped - PULL_THRESHOLD, PULL_OVERSHOOT);
}

/** 0..1: how much of the logo is drawn for a given content offset. */
export function pullProgress(offset: number): number {
  return Math.min(1, Math.max(0, offset / PULL_THRESHOLD));
}
