// Offline re-synthesis of the sample film's Web Audio effects (snd() in
// docs/design/film/wavecast-film.html), one WAV per effect kind, written to
// public/sfx/. Same parameters as the sample; the noise sources use a fixed
// seed, so the output is byte-identical on every run.
//
//   node scripts/synth-sfx.mjs
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const SR = 48000;
const OUT = join(dirname(fileURLToPath(import.meta.url)), "..", "public", "sfx");

function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Web Audio "bandpass" BiquadFilter (RBJ, constant 0 dB peak gain). */
function bandpass(x, freq, q) {
  const w0 = (2 * Math.PI * freq) / SR,
    alpha = Math.sin(w0) / (2 * q);
  const a0 = 1 + alpha,
    b0 = alpha / a0,
    b2 = -alpha / a0,
    a1 = (-2 * Math.cos(w0)) / a0,
    a2 = (1 - alpha) / a0;
  const y = new Float64Array(x.length);
  let x1 = 0,
    x2 = 0,
    y1 = 0,
    y2 = 0;
  for (let i = 0; i < x.length; i++) {
    const v = b0 * x[i] + b2 * x2 - a1 * y1 - a2 * y2;
    x2 = x1;
    x1 = x[i];
    y2 = y1;
    y1 = v;
    y[i] = v;
  }
  return y;
}

/** AudioParam automation: piecewise list of [time, value, "set" | "lin" | "exp"]. */
function envelope(points, t) {
  let v = points[0][1];
  for (let i = 1; i < points.length; i++) {
    const [t0, v0] = points[i - 1],
      [t1, v1, kind] = points[i];
    if (t < t0) break;
    if (t >= t1) {
      v = v1;
      continue;
    }
    const x = (t - t0) / (t1 - t0);
    v = kind === "exp" ? v0 * Math.pow(v1 / v0, x) : v0 + (v1 - v0) * x;
    break;
  }
  return v;
}

const seconds = (s) => new Float64Array(Math.ceil(SR * s));

// tick / key / tap: a short decaying noise burst through a band-pass.
function click(kind, seed) {
  const len = kind === "key" ? 0.03 : 0.015;
  const R = rng(seed);
  const buf = seconds(len + 0.05); // room for the filter to ring out
  const n = Math.ceil(SR * len);
  for (let i = 0; i < n; i++) buf[i] = (R() * 2 - 1) * Math.pow(1 - i / n, 4);
  const y = bandpass(buf, kind === "key" ? 2400 : kind === "tap" ? 1200 : 3800, 2);
  const g = kind === "tap" ? 0.5 : kind === "key" ? 0.16 : 0.2;
  return y.map((v) => v * g);
}

// noise: 5.5 s of band-passed static that fades in and out (tuning in).
function noise() {
  const dur = 5.5,
    R = rng(24);
  const buf = seconds(dur);
  for (let i = 0; i < buf.length; i++) buf[i] = R() * 2 - 1;
  const y = bandpass(buf, 1700, 0.7);
  const env = [[0, 0.0001], [0.3, 0.06, "lin"], [dur, 0.0001, "lin"]];
  return y.map((v, i) => v * envelope(env, i / SR));
}

// chime: two sine partials, the second 60 ms later.
function chime() {
  const out = seconds(1.3);
  [880, 1318.5].forEach((fr, k) => {
    const s0 = k * 0.06,
      env = [[0, 0.0001], [0.02, 0.1, "exp"], [1.1, 0.0001, "exp"]];
    for (let i = Math.round(s0 * SR); i < out.length; i++) {
      const t = i / SR - s0;
      if (t >= 1.2) break;
      out[i] += Math.sin(2 * Math.PI * fr * t) * envelope(env, t);
    }
  });
  return out;
}

// air: a sine sweeping 170 -> 300 Hz under a short swell (screen transitions).
function air() {
  const out = seconds(0.8);
  const fEnv = [[0, 170], [0.5, 300, "exp"]],
    gEnv = [[0, 0.0001], [0.12, 0.05, "exp"], [0.7, 0.0001, "exp"]];
  let phase = 0;
  for (let i = 0; i < out.length; i++) {
    const t = i / SR;
    out[i] = Math.sin(phase) * envelope(gEnv, t);
    phase += (2 * Math.PI * envelope(fEnv, t)) / SR;
  }
  return out;
}

function wav(samples) {
  const data = Buffer.alloc(samples.length * 2);
  samples.forEach((v, i) => data.writeInt16LE(Math.round(Math.max(-1, Math.min(1, v)) * 32767), i * 2));
  const h = Buffer.alloc(44);
  h.write("RIFF", 0);
  h.writeUInt32LE(36 + data.length, 4);
  h.write("WAVE", 8);
  h.write("fmt ", 12);
  h.writeUInt32LE(16, 16);
  h.writeUInt16LE(1, 20); // PCM
  h.writeUInt16LE(1, 22); // mono
  h.writeUInt32LE(SR, 24);
  h.writeUInt32LE(SR * 2, 28);
  h.writeUInt16LE(2, 32);
  h.writeUInt16LE(16, 34);
  h.write("data", 36);
  h.writeUInt32LE(data.length, 40);
  return Buffer.concat([h, data]);
}

mkdirSync(OUT, { recursive: true });
const sounds = { tick: click("tick", 1), key: click("key", 2), tap: click("tap", 3), noise: noise(), chime: chime(), air: air() };
for (const [name, samples] of Object.entries(sounds)) {
  writeFileSync(join(OUT, `${name}.wav`), wav(samples));
  const peak = samples.reduce((m, v) => Math.max(m, Math.abs(v)), 0);
  console.log(`${name}.wav  ${(samples.length / SR).toFixed(3)} s  peak ${(20 * Math.log10(peak)).toFixed(1)} dBFS`);
}
