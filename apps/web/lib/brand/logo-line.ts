// Draw-on state of the line-art logo (Frost-LogoDraw): a dot (the antenna tip) first, then the
// antenna, the body outline, the speaker dots, the window, the needle and the knob.

const clamp01 = (value: number) => Math.max(0, Math.min(1, value));

/** A stroke drawn from nothing while overall progress runs a..b (dash offset 1 → 0). */
function stroke(progress: number, a: number, b: number) {
  const t = clamp01((progress - a) / (b - a));
  return { offset: 1 - t, visible: t > 0 };
}

/** A solid shape that pops in, with a little overshoot, while progress runs a..b. */
function pop(progress: number, a: number, b: number): number {
  const t = clamp01((progress - a) / (b - a));
  if (t <= 0) return 0;
  const c1 = 1.70158;
  const c3 = c1 + 1;
  return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2;
}

export function logoDrawState(progress: number) {
  const p = clamp01(progress);
  return {
    tip: pop(p, 0, 0.1),
    antenna: stroke(p, 0.08, 0.2),
    body: stroke(p, 0.18, 0.55),
    window: pop(p, 0.58, 0.72),
    needle: stroke(p, 0.7, 0.82),
    knob: pop(p, 0.8, 0.92),
    /** The nine speaker dots, row by row, each popping a little after the last. */
    dots: Array.from({ length: 9 }, (_, index) => {
      const start = 0.5 + Math.floor(index / 3) * 0.07 + (index % 3) * 0.02;
      return pop(p, start, start + 0.12);
    }),
  };
}
