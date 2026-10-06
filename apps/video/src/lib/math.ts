// Pure time helpers. Every frame is a function of t (seconds); nothing here
// reads the clock or Math.random.
export const clamp = (x: number, lo = 0, hi = 1) => Math.max(lo, Math.min(hi, x));
/** Progress of t through [a, b], clamped to 0..1. */
export const p = (t: number, a: number, b: number) => clamp((t - a) / (b - a));
export const lerp = (a: number, b: number, x: number) => a + (b - a) * x;
/** Fast then slow (the brief's text easing). */
export const eo = (x: number) => 1 - Math.pow(1 - x, 3);
export const ei = (x: number) => x * x * x;
export const eio = (x: number) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);
export const sine = (x: number) => 0.5 - 0.5 * Math.cos(Math.PI * x);
/** Expo-ish out, slightly softer than eo; used for camera moves. */
export const eoq = (x: number) => 1 - Math.pow(1 - x, 4);

/** In/out envelope: rises over `fin` after a, falls over `fout` after b. */
export function env(t: number, a: number, b: number | null, fin = 0.8, fout = 0.6) {
  const i = eo(p(t, a, a + fin));
  const o = b == null ? 0 : ei(p(t, b, b + fout));
  return i * (1 - o);
}

/** Mulberry32, the same PRNG the product's cover generator uses. */
export function rng(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let x = Math.imul(a ^ (a >>> 15), 1 | a);
    x = (x + Math.imul(x ^ (x >>> 7), 61 | x)) ^ x;
    return ((x ^ (x >>> 14)) >>> 0) / 4294967296;
  };
}

export function mixHex(a: string, b: string, x: number): string {
  const pa = parseInt(a.slice(1), 16);
  const pb = parseInt(b.slice(1), 16);
  const ch = (v: number, s: number) => (v >> s) & 255;
  const m = (s: number) => Math.round(lerp(ch(pa, s), ch(pb, s), x));
  return "#" + ((1 << 24) | (m(16) << 8 << 8) | (m(8) << 8) | m(0)).toString(16).slice(1);
}

export const fmt = (n: number, d = 2) => n.toFixed(d);
