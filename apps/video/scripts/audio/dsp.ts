// Small offline DSP kit for the film's sound: stereo buffers, soft envelopes,
// filters, a few gentle synth voices and a Freeverb-style reverb.
// Everything is deterministic: noise comes from fixed-seed generators.
import { rng } from "../../src/lib/math";

export const SR = 48000;
export const TAU = Math.PI * 2;
export const midiHz = (m: number) => 440 * Math.pow(2, (m - 69) / 12);

export class Stereo {
  L: Float32Array;
  R: Float32Array;
  constructor(public seconds: number) {
    const n = Math.ceil(seconds * SR);
    this.L = new Float32Array(n);
    this.R = new Float32Array(n);
  }
  get length() {
    return this.L.length;
  }
  /** Equal-power pan, -1 (left) … 1 (right). */
  addMono(at: number, x: Float32Array, gain = 1, pan = 0) {
    const i0 = Math.round(at * SR);
    const a = ((Math.max(-1, Math.min(1, pan)) + 1) * Math.PI) / 4;
    const gl = Math.cos(a) * gain * Math.SQRT2;
    const gr = Math.sin(a) * gain * Math.SQRT2;
    for (let k = 0; k < x.length; k++) {
      const i = i0 + k;
      if (i < 0 || i >= this.L.length) continue;
      this.L[i] += x[k] * gl;
      this.R[i] += x[k] * gr;
    }
  }
  addStereo(at: number, s: Stereo, gain = 1) {
    const i0 = Math.round(at * SR);
    for (let k = 0; k < s.length; k++) {
      const i = i0 + k;
      if (i < 0 || i >= this.L.length) continue;
      this.L[i] += s.L[k] * gain;
      this.R[i] += s.R[k] * gain;
    }
  }
  /** Multiply by a gain curve g(t) (t in seconds from the buffer start). */
  shape(g: (t: number) => number, step = 64) {
    let gv = g(0);
    for (let i = 0; i < this.L.length; i++) {
      if (i % step === 0) gv = g(i / SR);
      this.L[i] *= gv;
      this.R[i] *= gv;
    }
  }
  peak() {
    let m = 0;
    for (let i = 0; i < this.L.length; i++) m = Math.max(m, Math.abs(this.L[i]), Math.abs(this.R[i]));
    return m;
  }
  scale(g: number) {
    for (let i = 0; i < this.L.length; i++) {
      this.L[i] *= g;
      this.R[i] *= g;
    }
  }
}

export const noiseGen = (seed: number) => {
  const R = rng(seed);
  return () => R() * 2 - 1;
};

/** Soft attack / exponential decay / short release, never a hard edge. */
export function envAD(n: number, attack: number, decay: number, release = 0.03) {
  const e = new Float32Array(n);
  const a = Math.max(1, attack * SR);
  const r = Math.max(1, release * SR);
  for (let i = 0; i < n; i++) {
    const t = i / SR;
    const up = i < a ? 0.5 - 0.5 * Math.cos((Math.PI * i) / a) : 1;
    const down = Math.exp(-t / decay);
    const tail = i > n - r ? 0.5 - 0.5 * Math.cos((Math.PI * (n - i)) / r) : 1;
    e[i] = up * down * tail;
  }
  return e;
}

/** Attack / sustain / release envelope for held notes. */
export function envASR(n: number, attack: number, hold: number, release: number, decay = 99) {
  const e = new Float32Array(n);
  const a = attack * SR;
  const h = hold * SR;
  for (let i = 0; i < n; i++) {
    const t = i / SR;
    let v = i < a ? 0.5 - 0.5 * Math.cos((Math.PI * i) / a) : 1;
    v *= Math.exp(-t / decay);
    if (i > h) v *= Math.max(0, 0.5 + 0.5 * Math.cos((Math.PI * Math.min(1, (i - h) / (release * SR))))) ;
    e[i] = v;
  }
  return e;
}

export type FilterType = "lp" | "hp" | "bp";
export function biquad(type: FilterType, f0: number, q = 0.707) {
  let b0 = 0, b1 = 0, b2 = 0, a1 = 0, a2 = 0;
  let x1 = 0, x2 = 0, y1 = 0, y2 = 0;
  const set = (f: number, qq = q) => {
    const w = (TAU * Math.min(f, SR * 0.45)) / SR;
    const alpha = Math.sin(w) / (2 * qq);
    const cw = Math.cos(w);
    const a0 = 1 + alpha;
    if (type === "lp") [b0, b1, b2] = [(1 - cw) / 2, 1 - cw, (1 - cw) / 2];
    else if (type === "hp") [b0, b1, b2] = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2];
    else [b0, b1, b2] = [alpha, 0, -alpha];
    b0 /= a0; b1 /= a0; b2 /= a0;
    a1 = (-2 * cw) / a0;
    a2 = (1 - alpha) / a0;
  };
  set(f0);
  const run = (x: number) => {
    const y = b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2;
    x2 = x1; x1 = x; y2 = y1; y1 = y;
    return y;
  };
  return Object.assign(run, { set });
}

export function filterBuf(x: Float32Array, type: FilterType, f: number, q = 0.707) {
  const fl = biquad(type, f, q);
  for (let i = 0; i < x.length; i++) x[i] = fl(x[i]);
  return x;
}

/** Time-varying low-pass over a stereo buffer: cutoff(t) in Hz. */
export function sweepLowpass(s: Stereo, cutoff: (t: number) => number) {
  const fl = biquad("lp", 1000, 0.6);
  const fr = biquad("lp", 1000, 0.6);
  for (let i = 0; i < s.length; i++) {
    if (i % 32 === 0) {
      const c = cutoff(i / SR);
      fl.set(c);
      fr.set(c);
    }
    s.L[i] = fl(s.L[i]);
    s.R[i] = fr(s.R[i]);
  }
}

/* ---------------- voices (mono, normalised to roughly ±1) ---------------- */

const tri = (ph: number) => 4 * Math.abs(ph - Math.floor(ph + 0.5)) - 1;

/** FM electric piano: warm tine, bell-ish attack that mellows. */
export function epiano(freq: number, dur: number, vel = 0.8, bright = 1) {
  const n = Math.ceil((dur + 0.5) * SR);
  const e = envASR(n, 0.006, dur, 0.35, 1.4);
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const t = i / SR;
    const idx = (0.9 + 1.4 * vel * bright) * Math.exp(-t * 3.2) + 0.25;
    const mod = Math.sin(TAU * freq * t) * idx;
    const tine = Math.sin(TAU * freq * 7.1 * t) * 0.12 * vel * bright * Math.exp(-t * 18);
    out[i] = (Math.sin(TAU * freq * t + mod) * 0.8 + Math.sin(TAU * freq * 2 * t) * 0.08 + tine) * e[i] * vel;
  }
  return out;
}

/** Soft pad: detuned triangles, low-passed, slow edges. */
export function pad(freq: number, dur: number, attack = 0.8, release = 1.4, cutoff = 1800) {
  const n = Math.ceil((dur + release) * SR);
  const e = envASR(n, attack, dur, release);
  const out = new Float32Array(n);
  const det = [-7, -2, 3, 8].map((c) => freq * Math.pow(2, c / 1200));
  for (let i = 0; i < n; i++) {
    const t = i / SR;
    let v = 0;
    for (let k = 0; k < det.length; k++) v += tri(det[k] * t + k * 0.21);
    out[i] = (v / det.length) * e[i];
  }
  return filterBuf(filterBuf(out, "lp", cutoff, 0.5), "hp", 60);
}

/** Marimba-like strike. */
export function marimba(freq: number, vel = 0.8) {
  const n = Math.ceil(0.9 * SR);
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const t = i / SR;
    const a = Math.min(1, i / (0.003 * SR));
    out[i] = a * vel * (Math.sin(TAU * freq * t) * Math.exp(-t * 5.5) + Math.sin(TAU * freq * 3.93 * t) * 0.22 * Math.exp(-t * 26) + Math.sin(TAU * freq * 9.2 * t) * 0.04 * Math.exp(-t * 60));
  }
  return out;
}

/** Soft FM bell. */
export function bell(freq: number, dur = 1.6, vel = 0.8) {
  const n = Math.ceil(dur * SR);
  const e = envAD(n, 0.008, dur / 3.2, 0.08);
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const t = i / SR;
    const idx = 1.6 * Math.exp(-t * 4) + 0.15;
    out[i] = Math.sin(TAU * freq * t + idx * Math.sin(TAU * freq * 3.5 * t)) * e[i] * vel;
  }
  return out;
}

/** Glassy ping: inharmonic partials, short. */
export function glass(freq: number, vel = 0.8) {
  const n = Math.ceil(0.7 * SR);
  const e = envAD(n, 0.005, 0.16, 0.06);
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const t = i / SR;
    out[i] = (Math.sin(TAU * freq * t) + 0.35 * Math.sin(TAU * freq * 2.76 * t) * Math.exp(-t * 10) + 0.12 * Math.sin(TAU * freq * 5.4 * t) * Math.exp(-t * 22)) * e[i] * vel * 0.7;
  }
  return out;
}

/** Plucked string (Karplus–Strong with a soft, averaged loop). */
export function pluck(freq: number, seed: number, vel = 0.8, dur = 1.2) {
  const n = Math.ceil(dur * SR);
  const p = Math.max(2, Math.round(SR / freq));
  const nz = noiseGen(seed);
  const line = new Float32Array(p);
  const lp = biquad("lp", Math.min(6000, freq * 6));
  for (let k = 0; k < p; k++) line[k] = lp(nz());
  const out = new Float32Array(n);
  let idx = 0;
  for (let i = 0; i < n; i++) {
    const a = line[idx];
    const b = line[(idx + 1) % p];
    const y = 0.4985 * (a + b);
    line[idx] = y;
    out[i] = a;
    idx = (idx + 1) % p;
  }
  const e = envAD(n, 0.004, dur / 2.5, 0.08);
  for (let i = 0; i < n; i++) out[i] *= e[i] * vel * 1.4;
  return out;
}

export function bass(freq: number, dur: number, vel = 0.8) {
  const n = Math.ceil((dur + 0.15) * SR);
  const e = envASR(n, 0.012, dur, 0.12, 2.5);
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const t = i / SR;
    out[i] = (Math.sin(TAU * freq * t) + 0.18 * Math.sin(TAU * freq * 2 * t)) * e[i] * vel;
  }
  return out;
}

export function kick(vel = 0.8) {
  const n = Math.ceil(0.35 * SR);
  const out = new Float32Array(n);
  let ph = 0;
  for (let i = 0; i < n; i++) {
    const t = i / SR;
    const f = 45 + 70 * Math.exp(-t * 28);
    ph += f / SR;
    out[i] = Math.sin(TAU * ph) * Math.exp(-t * 9) * Math.min(1, i / (0.002 * SR)) * vel;
  }
  return out;
}

export function snare(seed: number, vel = 0.6, tone = 1600, decay = 0.09) {
  const n = Math.ceil(0.3 * SR);
  const nz = noiseGen(seed);
  const bp = biquad("bp", tone, 0.9);
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const t = i / SR;
    out[i] = (bp(nz()) * 1.6 * Math.exp(-t / decay) + Math.sin(TAU * 210 * t) * 0.3 * Math.exp(-t * 30)) * Math.min(1, i / (0.002 * SR)) * vel;
  }
  return out;
}

export function hat(seed: number, vel = 0.4, decay = 0.035) {
  const n = Math.ceil(0.15 * SR);
  const nz = noiseGen(seed);
  const hp = biquad("hp", 7000, 0.7);
  const lp = biquad("lp", 12000, 0.7);
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const t = i / SR;
    out[i] = lp(hp(nz())) * Math.exp(-t / decay) * Math.min(1, i / (0.001 * SR)) * vel;
  }
  return out;
}

/* ---------------- reverb ---------------- */

/** Freeverb-style stereo reverb; returns the wet signal only. */
export function reverb(src: Stereo, { room = 0.7, damp = 0.4, predelay = 0.01 } = {}) {
  const scale = SR / 44100;
  const combs = [1116, 1188, 1277, 1356, 1422, 1491, 1557, 1617];
  const aps = [556, 441, 341, 225];
  const spread = 23;
  const out = new Stereo(src.seconds);
  const pd = Math.round(predelay * SR);
  for (const [ch, offset] of [[0, 0], [1, spread]] as const) {
    const input = ch === 0 ? src.L : src.R;
    const cbuf = combs.map((c) => new Float32Array(Math.round((c + offset) * scale)));
    const cidx = combs.map(() => 0);
    const cfs = combs.map(() => 0);
    const abuf = aps.map((a) => new Float32Array(Math.round((a + offset) * scale)));
    const aidx = aps.map(() => 0);
    const dst = ch === 0 ? out.L : out.R;
    const fb = room * 0.28 + 0.7;
    for (let i = 0; i < input.length; i++) {
      const x = (i - pd >= 0 ? (input[i - pd] + (ch === 0 ? src.R[i - pd] : src.L[i - pd])) : 0) * 0.015;
      let y = 0;
      for (let c = 0; c < cbuf.length; c++) {
        const b = cbuf[c];
        const v = b[cidx[c]];
        y += v;
        cfs[c] = v * (1 - damp) + cfs[c] * damp;
        b[cidx[c]] = x + cfs[c] * fb;
        cidx[c] = (cidx[c] + 1) % b.length;
      }
      for (let a = 0; a < abuf.length; a++) {
        const b = abuf[a];
        const v = b[aidx[a]];
        b[aidx[a]] = y + v * 0.5;
        y = v - y;
        aidx[a] = (aidx[a] + 1) % b.length;
      }
      dst[i] = y;
    }
  }
  return out;
}

/* ---------------- loudness (ITU-R BS.1770 / EBU R128 integrated) ---------------- */

export function lufs(s: Stereo) {
  // K-weighting: high shelf + high pass (48 kHz coefficients from BS.1770).
  const kw = () => {
    const st = [[1.53512485958697, -2.69169618940638, 1.19839281085285, -1.69065929318241, 0.73248077421585], [1.0, -2.0, 1.0, -1.99004745483398, 0.99007225036621]];
    const z = st.map(() => [0, 0, 0, 0]);
    return (x: number) => {
      let v = x;
      st.forEach(([b0, b1, b2, a1, a2], k) => {
        const [x1, x2, y1, y2] = z[k];
        const y = b0 * v + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2;
        z[k] = [v, x1, y, y1];
        v = y;
      });
      return v;
    };
  };
  const fl = kw();
  const fr = kw();
  const sq = new Float64Array(s.length);
  for (let i = 0; i < s.length; i++) {
    const l = fl(s.L[i]);
    const r = fr(s.R[i]);
    sq[i] = l * l + r * r;
  }
  const block = Math.round(0.4 * SR);
  const hop = Math.round(0.1 * SR);
  const powers: number[] = [];
  for (let i = 0; i + block <= sq.length; i += hop) {
    let sum = 0;
    for (let k = i; k < i + block; k++) sum += sq[k];
    powers.push(sum / block);
  }
  const L = (p: number) => -0.691 + 10 * Math.log10(p);
  const abs = powers.filter((p) => L(p) > -70);
  if (!abs.length) return -Infinity;
  const relGate = L(abs.reduce((a, b) => a + b, 0) / abs.length) - 10;
  const rel = abs.filter((p) => L(p) > relGate);
  return L(rel.reduce((a, b) => a + b, 0) / rel.length);
}

/* ---------------- WAV ---------------- */

export function wav(s: Stereo, from = 0, seconds = s.seconds) {
  const i0 = Math.round(from * SR);
  const n = Math.round(seconds * SR);
  const buf = Buffer.alloc(44 + n * 4);
  buf.write("RIFF", 0);
  buf.writeUInt32LE(36 + n * 4, 4);
  buf.write("WAVEfmt ", 8);
  buf.writeUInt32LE(16, 16);
  buf.writeUInt16LE(1, 20);
  buf.writeUInt16LE(2, 22);
  buf.writeUInt32LE(SR, 24);
  buf.writeUInt32LE(SR * 4, 28);
  buf.writeUInt16LE(4, 32);
  buf.writeUInt16LE(16, 34);
  buf.write("data", 36);
  buf.writeUInt32LE(n * 4, 40);
  for (let k = 0; k < n; k++) {
    const i = i0 + k;
    const l = i < s.length ? s.L[i] : 0;
    const r = i < s.length ? s.R[i] : 0;
    buf.writeInt16LE(Math.round(Math.max(-1, Math.min(1, l)) * 32767), 44 + k * 4);
    buf.writeInt16LE(Math.round(Math.max(-1, Math.min(1, r)) * 32767), 46 + k * 4);
  }
  return buf;
}
