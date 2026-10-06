// Voices for the lazy-jazz score: soft e-piano with tremolo and chorus,
// round sine bass with the odd glide, a breathy flute-like lead, brushes and
// a soft kick. All return mono buffers except the e-piano (stereo pair).
import { biquad, envAD, envASR, noiseGen, SR, TAU } from "./dsp";

/** Mellow FM e-piano, rendered as a slightly detuned stereo pair with tremolo (chorus-like width). */
export function keys(freq: number, dur: number, vel = 0.7): [Float32Array, Float32Array] {
  const n = Math.ceil((dur + 0.8) * SR);
  const e = envASR(n, 0.012, dur, 0.6, 2.2);
  const out: [Float32Array, Float32Array] = [new Float32Array(n), new Float32Array(n)];
  const det = [1.0018, 0.9982];
  for (let c = 0; c < 2; c++) {
    const f = freq * det[c];
    for (let i = 0; i < n; i++) {
      const t = i / SR;
      const idx = (0.5 + 0.7 * vel) * Math.exp(-t * 2.5) + 0.15;
      const trem = 1 - 0.12 * (0.5 + 0.5 * Math.sin(TAU * 4.6 * t + c * Math.PI * 0.7));
      const tine = Math.sin(TAU * f * 6.9 * t) * 0.05 * vel * Math.exp(-t * 14);
      out[c][i] = (Math.sin(TAU * f * t + idx * Math.sin(TAU * f * t)) * 0.85 + tine) * e[i] * vel * trem;
    }
  }
  return out;
}

/** Round sine bass; `slide` semitones below, gliding up over the first 60 ms. */
export function roundBass(freq: number, dur: number, vel = 0.8, slide = 0) {
  const n = Math.ceil((dur + 0.2) * SR);
  const e = envASR(n, 0.015, dur, 0.15, 3);
  const out = new Float32Array(n);
  let ph = 0;
  for (let i = 0; i < n; i++) {
    const t = i / SR;
    const f = freq * Math.pow(2, (-slide * Math.exp(-t / 0.03)) / 12);
    ph += f / SR;
    out[i] = (Math.sin(TAU * ph) + 0.08 * Math.sin(TAU * ph * 2)) * e[i] * vel;
  }
  return out;
}

/** Breathy flute-like lead: near-sine, delayed vibrato, a puff of air on the attack. */
export function flute(freq: number, dur: number, vel = 0.7, seed = 1) {
  const n = Math.ceil((dur + 0.3) * SR);
  const e = envASR(n, 0.06, dur, 0.25);
  const nz = noiseGen(seed);
  const air = biquad("bp", freq * 2, 1.5);
  const out = new Float32Array(n);
  let ph = 0;
  for (let i = 0; i < n; i++) {
    const t = i / SR;
    const vib = 1 + 0.004 * Math.min(1, t / 0.4) * Math.sin(TAU * 5 * t);
    ph += (freq * vib) / SR;
    const tone = Math.sin(TAU * ph) + 0.12 * Math.sin(TAU * ph * 2) + 0.04 * Math.sin(TAU * ph * 3);
    out[i] = (tone + air(nz()) * (0.25 + 0.5 * Math.exp(-t * 12))) * e[i] * vel;
  }
  return out;
}

/** Brush swish on the hat. */
export function brush(seed: number, vel = 0.4, len = 0.09) {
  const n = Math.ceil((len + 0.05) * SR);
  const nz = noiseGen(seed);
  const bp = biquad("bp", 5200, 0.7);
  const e = envAD(n, 0.006, len / 2.5, 0.03);
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) out[i] = bp(nz()) * e[i] * vel * 1.6;
  return out;
}

/** Brushed snare: soft noise burst with a low body. */
export function brushSnare(seed: number, vel = 0.5) {
  const n = Math.ceil(0.3 * SR);
  const nz = noiseGen(seed);
  const bp = biquad("bp", 2400, 0.6);
  const e = envAD(n, 0.008, 0.08, 0.05);
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const t = i / SR;
    out[i] = (bp(nz()) * 1.5 + Math.sin(TAU * 190 * t) * 0.35 * Math.exp(-t * 25)) * e[i] * vel;
  }
  return out;
}

/** Soft, short kick. */
export function softKick(vel = 0.7) {
  const n = Math.ceil(0.3 * SR);
  const out = new Float32Array(n);
  let ph = 0;
  const lp = biquad("lp", 400);
  for (let i = 0; i < n; i++) {
    const t = i / SR;
    ph += (48 + 40 * Math.exp(-t * 35)) / SR;
    out[i] = lp(Math.sin(TAU * ph) * Math.exp(-t * 10) * Math.min(1, i / (0.004 * SR))) * vel * 1.3;
  }
  return out;
}

/** Soft bell-like arpeggio note. */
export function arpNote(freq: number, vel = 0.5) {
  const n = Math.ceil(1.2 * SR);
  const e = envAD(n, 0.01, 0.35, 0.1);
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const t = i / SR;
    out[i] = (Math.sin(TAU * freq * t + 0.6 * Math.exp(-t * 6) * Math.sin(TAU * freq * 2 * t)) + 0.15 * Math.sin(TAU * freq * 3 * t) * Math.exp(-t * 8)) * e[i] * vel;
  }
  return out;
}
