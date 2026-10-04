// Easing helpers, identical to the sample's render(t) helpers.
export const clamp = (x: number) => Math.max(0, Math.min(1, x));
export const p = (t: number, a: number, b: number) => clamp((t - a) / (b - a));
export const eo = (x: number) => 1 - Math.pow(1 - x, 3);
export const eio = (x: number) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);
export const ei = (x: number) => x * x * x;
export const lerp = (a: number, b: number, x: number) => a + (b - a) * x;
export const r2 = (n: number) => Math.round(n * 100) / 100;

/** Seeded PRNG (mulberry32), the only randomness allowed in the film. */
export function rng(seed: number) {
  let a = seed >>> 0;
  return function () {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
