// Offline sound-effect bed (FILM_BRIEF.md §4): no voice, no music. Every event
// time comes from src/timeline.ts, so picture and sound cannot drift. Output:
// public/sfx.wav (48 kHz, 16-bit stereo). Deterministic: fixed-seed noise.
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { AFTERNOON, COLD, DURATION, END, MORNING, NEXT, NIGHT } from "../src/timeline";
import { coldFreq, STATION_HITS } from "../src/scenes/coldCurve";
import { tuneFreq } from "../src/scenes/afternoonCurve";
import { TYPED } from "../src/content";
import { rng } from "../src/lib/math";

const SR = 48000;
const N = Math.ceil(DURATION * SR);
const L = new Float32Array(N);
const R = new Float32Array(N);
const noise = rng(20261005);
const white = () => noise() * 2 - 1;

/** RBJ biquad. */
function biquad(type: "bp" | "lp" | "hp", f0: number, q: number) {
  const w = (2 * Math.PI * f0) / SR;
  const alpha = Math.sin(w) / (2 * q);
  const cw = Math.cos(w);
  let b0: number, b1: number, b2: number;
  if (type === "bp") [b0, b1, b2] = [alpha, 0, -alpha];
  else if (type === "lp") [b0, b1, b2] = [(1 - cw) / 2, 1 - cw, (1 - cw) / 2];
  else [b0, b1, b2] = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2];
  const a0 = 1 + alpha;
  const a1 = -2 * cw;
  const a2 = 1 - alpha;
  let x1 = 0, x2 = 0, y1 = 0, y2 = 0;
  return (x: number) => {
    const y = (b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2) / a0;
    x2 = x1; x1 = x; y2 = y1; y1 = y;
    return y;
  };
}

const at = (t: number) => Math.max(0, Math.round(t * SR));
function add(i: number, v: number, pan = 0) {
  if (i < 0 || i >= N) return;
  L[i] += v * (1 - Math.max(0, pan));
  R[i] += v * (1 + Math.min(0, pan));
}

/* --- radio static: band-passed noise around 1.9 kHz, 0.4–6.6 s, dips on stations --- */
{
  const bp = biquad("bp", 1900, 0.8);
  const [s0, s1] = COLD.static;
  for (let i = at(s0); i < at(s1 + 0.15); i++) {
    const t = i / SR;
    const fadeIn = Math.min(1, (t - s0) / 0.5);
    const fadeOut = Math.min(1, Math.max(0, (s1 + 0.15 - t) / 0.25));
    const f = coldFreq(t);
    const onStation = STATION_HITS.some((h) => Math.abs(h.freq - f) < 0.35);
    const g = 0.09 * fadeIn * fadeOut * (onStation ? 0.35 : 1);
    const v = bp(white()) * g * 3;
    add(i, v);
  }
}

/* --- dial ticks: every 0.5 MHz crossing (cold sweep, afternoon drag and alignment) --- */
function tick(t: number, gain = 0.22) {
  const len = 0.012;
  const bp = biquad("bp", 3800, 2);
  for (let k = 0; k < len * SR; k++) add(at(t) + k, bp(white()) * gain * Math.pow(1 - k / (len * SR), 4) * 4);
}
function crossings(fn: (t: number) => number, a: number, b: number) {
  let prev = Math.floor(fn(a) * 2);
  for (let t = a; t < b; t += 1 / 240) {
    const v = Math.floor(fn(t) * 2);
    if (v !== prev) tick(t);
    prev = v;
  }
}
crossings(coldFreq, COLD.sweep[0], COLD.lock[1]);
crossings(tuneFreq, AFTERNOON.drag[0], AFTERNOON.align[1] + 0.5);

/* --- station fragments: soft triangle chord, low-passed, ~0.9 s --- */
const tri = (ph: number) => 2 * Math.abs(2 * (ph - Math.floor(ph + 0.5))) - 1;
const CHORDS = [
  [220, 277.18, 329.63],
  [196, 246.94, 293.66],
  [174.61, 220, 261.63],
  [164.81, 207.65, 246.94],
];
STATION_HITS.slice(0, 4).forEach((h, n) => {
  const lp = biquad("lp", 1400, 0.7);
  const dur = 0.9;
  for (let k = 0; k < dur * SR; k++) {
    const t = k / SR;
    const env = Math.min(1, t / 0.06) * Math.exp(-t * 3.2);
    let v = 0;
    for (const f of CHORDS[n]) v += tri(f * t);
    add(at(h.at - 0.05) + k, lp(v) * 0.055 * env, (n % 2 ? 0.25 : -0.25));
  }
});

/* --- lock chime: 523, 784, 1047 Hz in turn, ~2 s decay --- */
[523.25, 783.99, 1046.5].forEach((f, n) => {
  const t0 = COLD.lock[0] + 0.06 + n * 0.12;
  for (let k = 0; k < 2.2 * SR; k++) {
    const t = k / SR;
    const env = Math.min(1, t / 0.008) * Math.exp(-t * 2.4);
    add(at(t0) + k, Math.sin(2 * Math.PI * f * t) * 0.07 * env);
  }
});

/* --- taps and keys --- */
function click(t: number, f: number, gain: number, len: number) {
  const bp = biquad("bp", f, 2);
  for (let k = 0; k < len * SR; k++) add(at(t) + k, bp(white()) * gain * Math.pow(1 - k / (len * SR), 4) * 4);
}
const mid = ([a, b]: readonly number[]) => (a + b) / 2;
[MORNING.tap, MORNING.tabTap, AFTERNOON.ctaTap, NIGHT.routeTap].forEach((g) => click(mid(g), 1200, 0.32, 0.018));
const chars = [...TYPED].length;
for (let n = 1; n <= chars; n++) click(AFTERNOON.typing[0] + (n / chars) * (AFTERNOON.typing[1] - AFTERNOON.typing[0]) - 0.05, 2400, 0.1, 0.03);

/* --- light air on transitions --- */
function air(t: number, gain = 0.05) {
  const bp = biquad("bp", 600, 0.6);
  const dur = 0.9;
  for (let k = 0; k < dur * SR; k++) {
    const x = k / (dur * SR);
    const env = Math.sin(Math.PI * Math.pow(x, 0.7));
    add(at(t) + k, bp(white()) * gain * env * 3, (x - 0.5) * 0.6);
  }
}
[COLD.dawn[0], MORNING.open[0], MORNING.collapse[0], AFTERNOON.light[0], AFTERNOON.explode[0], AFTERNOON.collapse[0], AFTERNOON.phoneOut[0], NIGHT.phoneIn[0], NIGHT.route[0], NIGHT.collapse[0], NEXT.pullBack[0], END.gather[0]].forEach((t) => air(t));

/* --- rain: low-passed noise for the whole night --- */
{
  const lpL = biquad("lp", 2600, 0.5);
  const lpR = biquad("lp", 2600, 0.5);
  const hpL = biquad("hp", 300, 0.5);
  const hpR = biquad("hp", 300, 0.5);
  const [r0] = NIGHT.rainIn;
  const [, r1] = NIGHT.rainOut;
  for (let i = at(r0); i < at(r1); i++) {
    const t = i / SR;
    const env = Math.min(1, (t - r0) / 1.8) * Math.min(1, (r1 - t) / 2.4);
    const g = 0.035 * env;
    L[i] += hpL(lpL(white())) * g * 3;
    R[i] += hpR(lpR(white())) * g * 3;
  }
}

/* --- write --- */
const peak = Math.max(...Array.from({ length: 2 }, (_, c) => (c ? R : L).reduce((m, v) => Math.max(m, Math.abs(v)), 0)));
const scale = peak > 0.9 ? 0.9 / peak : 1;
const buf = Buffer.alloc(44 + N * 4);
buf.write("RIFF", 0);
buf.writeUInt32LE(36 + N * 4, 4);
buf.write("WAVEfmt ", 8);
buf.writeUInt32LE(16, 16);
buf.writeUInt16LE(1, 20);
buf.writeUInt16LE(2, 22);
buf.writeUInt32LE(SR, 24);
buf.writeUInt32LE(SR * 4, 28);
buf.writeUInt16LE(4, 32);
buf.writeUInt16LE(16, 34);
buf.write("data", 36);
buf.writeUInt32LE(N * 4, 40);
for (let i = 0; i < N; i++) {
  buf.writeInt16LE(Math.round(Math.max(-1, Math.min(1, L[i] * scale)) * 32767), 44 + i * 4);
  buf.writeInt16LE(Math.round(Math.max(-1, Math.min(1, R[i] * scale)) * 32767), 46 + i * 4);
}
mkdirSync(join(__dirname, "../public"), { recursive: true });
writeFileSync(join(__dirname, "../public/sfx.wav"), buf);
console.log(`sfx.wav: ${DURATION}s, peak ${(peak * scale).toFixed(2)}`);
