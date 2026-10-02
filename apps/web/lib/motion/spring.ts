// Small critically-damped-ish spring (MOTION.md §2): stiffness 380, damping 36,
// mass 1 — almost no overshoot, settles in ~350–400ms. Takes the release
// velocity as its initial velocity so a fling and a slow release feel different.

export type SpringParams = { stiffness: number; damping: number; mass: number };
export const SPRING: SpringParams = { stiffness: 380, damping: 36, mass: 1 };

export type SpringState = { position: number; velocity: number };

const MAX_STEP_MS = 4;

/**
 * Advances a spring towards `target` by `dtMs` (semi-implicit Euler with small
 * sub-steps). Velocity is in units per millisecond.
 */
export function springStep(
  state: SpringState,
  target: number,
  dtMs: number,
  params: SpringParams = SPRING,
): SpringState {
  let { position, velocity } = state;
  let remaining = Math.max(0, dtMs);
  while (remaining > 0) {
    const stepMs = Math.min(MAX_STEP_MS, remaining);
    const dt = stepMs / 1000; // seconds
    const vSec = velocity * 1000;
    const force = -params.stiffness * (position - target) - params.damping * vSec;
    const nextVSec = vSec + (force / params.mass) * dt;
    position += nextVSec * dt;
    velocity = nextVSec / 1000;
    remaining -= stepMs;
  }
  return { position, velocity };
}

export function springAtRest(state: SpringState, target: number, epsilon = 0.5): boolean {
  return Math.abs(state.position - target) < epsilon && Math.abs(state.velocity) < 0.01;
}

/** Simulated time for a spring to settle (for tests / tuning). */
export function springSettleMs(from: number, to: number, velocity = 0, params: SpringParams = SPRING): number {
  let state: SpringState = { position: from, velocity };
  for (let elapsed = 0; elapsed < 5000; elapsed += 16) {
    state = springStep(state, to, 16, params);
    if (springAtRest(state, to)) return elapsed + 16;
  }
  return 5000;
}

export type Cancel = () => void;

/**
 * Runs a spring on requestAnimationFrame using real elapsed time. Returns a
 * cancel function so a gesture can grab the element mid-animation.
 */
export function animateSpring(options: {
  from: number;
  to: number;
  velocity?: number;
  epsilon?: number;
  onUpdate: (position: number, velocity: number) => void;
  onComplete?: () => void;
  params?: SpringParams;
}): Cancel {
  let state: SpringState = { position: options.from, velocity: options.velocity ?? 0 };
  let last = performance.now();
  let frame = requestAnimationFrame(function tick(now) {
    const dt = Math.min(64, now - last);
    last = now;
    state = springStep(state, options.to, dt, options.params);
    if (springAtRest(state, options.to, options.epsilon)) {
      options.onUpdate(options.to, 0);
      options.onComplete?.();
      return;
    }
    options.onUpdate(state.position, state.velocity);
    frame = requestAnimationFrame(tick);
  });
  return () => cancelAnimationFrame(frame);
}
