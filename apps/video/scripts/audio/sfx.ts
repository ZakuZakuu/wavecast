// Sound effects: soft attacks, short tails, a small room, panned to where the
// thing is on screen. Pitches come from D major pentatonic; each station has
// its note (88.7 D, 93.1 E, 97.4 F#, 101.5 A, 105.8 B).
import { AFTERNOON, COLD, DURATION, END, MORNING, NEXT, NIGHT } from "../../src/timeline";
import { TYPED } from "../../src/content";
import { coldFreq, STATION_HITS } from "../../src/scenes/coldCurve";
import { tuneFreq } from "../../src/scenes/afternoonCurve";
import { TILES, tileAppearAt } from "../../src/scenes/wallLayout";
import { BREAKDOWN } from "../../src/content";
import { clamp, rng } from "../../src/lib/math";
import { bell, biquad, envAD, filterBuf, glass, marimba, midiHz, noiseGen, pluck, reverb, SR, Stereo, TAU } from "./dsp";
import { motifFragment } from "./music";

export const STATION_NOTE: Record<string, number> = { "88.7": 74, "93.1": 76, "97.4": 78, "101.5": 81, "105.8": 83 };
const PENTA = [62, 64, 66, 69, 71];
const pan = (x: number) => clamp((x - 960) / 960, -1, 1) * 0.85;
const PHONE_X = 1180;
const DIAL_X = (f: number) => 160 + ((f - 86) / 22) * 1600;

/* ---------------- voices ---------------- */

/** Light woody tap with a small downward pitch bend and a tiny noise transient. */
function tap(seed: number) {
  const n = Math.ceil(0.12 * SR);
  const nz = noiseGen(seed);
  const hp = biquad("hp", 3000);
  const out = new Float32Array(n);
  let ph = 0;
  for (let i = 0; i < n; i++) {
    const t = i / SR;
    const f = 820 * (0.72 + 0.28 * Math.exp(-t * 60));
    ph += f / SR;
    out[i] = Math.sin(TAU * ph) * Math.exp(-t * 45) * Math.min(1, i / (0.004 * SR)) + hp(nz()) * 0.35 * Math.exp(-t * 900);
  }
  return out;
}

/** Muffled dial tick. */
function tick(seed: number) {
  const n = Math.ceil(0.06 * SR);
  const nz = noiseGen(seed);
  const lp = biquad("lp", 900);
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const t = i / SR;
    out[i] = (Math.sin(TAU * 210 * t) * 0.8 + lp(nz()) * 0.6) * Math.exp(-t * 90) * Math.min(1, i / (0.003 * SR));
  }
  return out;
}

/** Soft key: band-passed click, pitch varies a little per press. */
function key(seed: number) {
  const R = rng(seed);
  const n = Math.ceil(0.05 * SR);
  const nz = noiseGen(seed + 1);
  const bp = biquad("bp", 2000 + R() * 900, 1.2);
  const f = 700 + R() * 250;
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const t = i / SR;
    out[i] = (bp(nz()) * 1.4 + Math.sin(TAU * f * t) * 0.35) * Math.exp(-t * 110) * Math.min(1, i / (0.003 * SR));
  }
  return out;
}

/** Filtered-noise sweep (transitions); `up` sweeps bright, otherwise darker. */
function whoosh(seed: number, dur: number, up: boolean) {
  const n = Math.ceil(dur * SR);
  const nz = noiseGen(seed);
  const bp = biquad("bp", 600, 0.8);
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const x = i / n;
    if (i % 32 === 0) bp.set(up ? 300 * Math.pow(12, x) : 3000 * Math.pow(1 / 10, x));
    out[i] = bp(nz()) * Math.sin(Math.PI * Math.pow(x, up ? 1.2 : 0.7)) * 1.4;
  }
  return out;
}

function lowThump(freq = 70) {
  const n = Math.ceil(0.5 * SR);
  const e = envAD(n, 0.015, 0.14, 0.08);
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) out[i] = Math.sin((TAU * freq * i) / SR) * e[i];
  return out;
}

/** Glide (breakdown collapse): quick downward sine slide. */
function glide(from: number, to: number, dur: number) {
  const n = Math.ceil(dur * SR);
  const e = envAD(n, 0.01, dur / 2, 0.05);
  const out = new Float32Array(n);
  let ph = 0;
  for (let i = 0; i < n; i++) {
    const x = i / n;
    ph += (from * Math.pow(to / from, x)) / SR;
    out[i] = (Math.sin(TAU * ph) + 0.3 * Math.sin(TAU * ph * 2)) * e[i];
  }
  return out;
}

/** Radio static with sparse crackles. */
function staticBed(seed: number, dur: number) {
  const n = Math.ceil(dur * SR);
  const nz = noiseGen(seed);
  const R = rng(seed + 7);
  const bp = biquad("bp", 1900, 0.7);
  const out = new Float32Array(n);
  let crackle = 0;
  for (let i = 0; i < n; i++) {
    if (R() < 18 / SR) crackle = 0.6 + R() * 0.8;
    crackle *= 0.992;
    out[i] = bp(nz()) * 0.9 + nz() * crackle * 0.25;
  }
  return out;
}

/** Rain: two decorrelated low-passed noise beds. */
function rainBed(seed: number, dur: number) {
  const s = new Stereo(dur);
  for (const [ch, sd] of [[s.L, seed], [s.R, seed + 1]] as const) {
    const nz = noiseGen(sd);
    const lp = biquad("lp", 2400, 0.5);
    const hp = biquad("hp", 250, 0.5);
    for (let i = 0; i < ch.length; i++) ch[i] = hp(lp(nz())) * 0.9;
  }
  return s;
}

function drop(freq: number) {
  const n = Math.ceil(0.12 * SR);
  const out = new Float32Array(n);
  let ph = 0;
  for (let i = 0; i < n; i++) {
    const t = i / SR;
    ph += (freq * (1 + 0.6 * Math.exp(-t * 80))) / SR;
    out[i] = Math.sin(TAU * ph) * Math.exp(-t * 55) * Math.min(1, i / (0.003 * SR));
  }
  return out;
}

/* ---------------- placement ---------------- */

export function buildSfx() {
  const dry = new Stereo(DURATION + 2);
  const send = new Stereo(DURATION + 2);
  const put = (t: number, x: Float32Array, gain: number, p = 0, rv = 0.25) => {
    dry.addMono(t, x, gain, p);
    if (rv > 0) send.addMono(t, x, gain * rv, p);
  };

  // Cold open: static, ticks, a radio-filtered motif fragment and a bell at each station, then the lock.
  const [s0, s1] = COLD.static;
  const stat = staticBed(11, s1 - s0 + 0.3);
  for (let i = 0; i < stat.length; i++) {
    const t = s0 + i / SR;
    const fade = Math.min(1, (t - s0) / 0.6, Math.max(0, (s1 + 0.3 - t) / 0.3));
    const near = STATION_HITS.some((h) => Math.abs(h.freq - coldFreq(t)) < 0.3) ? 0.35 : 1;
    stat[i] *= fade * near;
  }
  put(s0, stat, 0.16, 0, 0);
  const ticks = (fn: (t: number) => number, a: number, b: number, panOf: (f: number) => number) => {
    let prev = Math.floor(fn(a) * 2);
    let n = 0;
    for (let t = a; t < b; t += 1 / 480) {
      const v = Math.floor(fn(t) * 2);
      if (v !== prev) put(t, tick(300 + n++), 0.35, panOf(fn(t)), 0.1);
      prev = v;
    }
  };
  ticks(coldFreq, COLD.sweep[0], COLD.lock[1], (f) => pan(DIAL_X(f)));
  STATION_HITS.slice(0, 4).forEach((h, k) => {
    const note = STATION_NOTE[h.freq.toFixed(1)];
    const frag = motifFragment(note);
    const mono = new Float32Array(frag.length);
    for (let i = 0; i < mono.length; i++) mono[i] = (frag.L[i] + frag.R[i]) / 2;
    filterBuf(filterBuf(filterBuf(mono, "hp", 300, 0.7), "lp", 3000, 0.7), "lp", 3000, 0.7);
    const fade = envAD(mono.length, 0.02, 0.6, 0.15);
    for (let i = 0; i < mono.length; i++) mono[i] *= fade[i];
    put(h.at - 0.08, mono, 0.9, pan(DIAL_X(h.freq)), 0.2);
    put(h.at, bell(midiHz(note), 1.0, 0.5), 0.22, pan(DIAL_X(h.freq)), 0.3);
    void k;
  });
  // Lock: rising arpeggio D–F#–A with a reverb tail.
  [74, 78, 81].forEach((m, i) => put(COLD.lock[0] + 0.05 + i * 0.11, bell(midiHz(m), 2.0, 0.7), 0.3, pan(DIAL_X(88.7)) * 0.6, 0.7));

  // Transitions (filtered-noise sweeps) and drawers (+ a soft low note on open).
  const sweeps: Array<[number, number, boolean]> = [
    [COLD.dawn[0], 1.0, true],
    [AFTERNOON.light[0], 1.0, true],
    [NIGHT.light[0], 1.2, false],
    [NIGHT.light2[0], 1.4, true],
    [AFTERNOON.phoneOut[0], 0.8, false],
    [NIGHT.phoneIn[0], 0.9, true],
    [NEXT.pullBack[0], 1.0, true],
  ];
  sweeps.forEach(([t, d, up], i) => put(t, whoosh(500 + i, d, up), 0.22, 0, 0.2));
  const drawers: Array<[number, boolean]> = [
    [MORNING.open[0], true],
    [MORNING.collapse[0], false],
    [NIGHT.route[0], true],
    [NIGHT.route[1], false],
    [NIGHT.collapse[0], false],
    [AFTERNOON.tuningIn, true],
  ];
  drawers.forEach(([t, open], i) => {
    put(t, whoosh(600 + i, 0.55, open), 0.2, pan(PHONE_X), 0.15);
    if (open) put(t + 0.02, lowThump(open ? 73.4 : 55), 0.28, pan(PHONE_X), 0);
  });

  // Taps.
  const mid = ([a, b]: readonly number[]) => (a + b) / 2;
  ([
    [MORNING.tap, 1089],
    [MORNING.tabTap, PHONE_X],
    [AFTERNOON.ctaTap, PHONE_X],
    [NIGHT.routeTap, 1317],
  ] as Array<[readonly number[], number]>).forEach(([g, x], i) => put(mid(g), tap(700 + i), 0.5, pan(x), 0.2));

  // Afternoon dial: ticks, and the station's bell whenever the needle settles on one.
  ticks(tuneFreq, AFTERNOON.drag[0], AFTERNOON.align[1] + 0.5, () => pan(PHONE_X));
  let last = "";
  for (let t = AFTERNOON.drag[0]; t < AFTERNOON.align[1] + 0.6; t += 1 / 120) {
    const f = tuneFreq(t);
    const hit = Object.keys(STATION_NOTE).find((k) => Math.abs(Number(k) - f) < 0.08) ?? "";
    if (hit && hit !== last) put(t, bell(midiHz(STATION_NOTE[hit]), 1.1, 0.5), 0.22, pan(PHONE_X), 0.3);
    last = hit || (Math.min(...Object.keys(STATION_NOTE).map((k) => Math.abs(Number(k) - f))) > 0.3 ? "" : last);
  }

  // Typing.
  const chars = [...TYPED].length;
  for (let n = 0; n < chars; n++) put(AFTERNOON.typing[0] + ((n + 1) / chars) * (AFTERNOON.typing[1] - AFTERNOON.typing[0]) - 0.05, key(900 + n), 0.28, pan(PHONE_X), 0.12);

  // Home covers: a glassy ping as each one builds.
  const cardX = [1089, 1271, 1089, 1271];
  [0, 1, 2, 3].forEach((i) => {
    put(MORNING.coversAt + i * MORNING.coverStagger + 0.1, glass(midiHz([86, 88, 90, 93][i]), 0.7), 0.16, pan(cardX[i]), 0.35);
    put(NEXT.coversAt + i * NEXT.coverStagger + 0.1, glass(midiHz([88, 90, 93, 95][i]), 0.7), 0.16, pan(cardX[i]), 0.35);
  });

  // Breakdown: six rising plucks as the cards light, a quick downward glide on the way back.
  BREAKDOWN.forEach((_, i) => put(AFTERNOON.cardsLit + i * AFTERNOON.cardStep, pluck(midiHz([62, 64, 66, 69, 71, 74][i]), 1100 + i, 0.8, 1.4), 0.35, pan(1560), 0.35));
  put(AFTERNOON.collapse[0], glide(midiHz(86), midiHz(62), 0.45), 0.12, pan(1300), 0.3);

  // Rain: a bed for the whole night plus the odd drop.
  const [r0] = NIGHT.rainIn;
  const [, r1] = NIGHT.rainOut;
  const rain = rainBed(31, r1 - r0);
  rain.shape((t) => Math.min(1, t / 1.8, (r1 - r0 - t) / 2.4));
  dry.addStereo(r0, rain, 0.05);
  const R = rng(4242);
  for (let t = r0 + 1; t < r1 - 1; t += 0.35 + R() * 1.2) put(t, drop(1800 + R() * 1400), 0.06 + R() * 0.05, R() * 1.6 - 0.8, 0.3);

  // Cover wall: one pentatonic note per cover, three octaves (top rows higher),
  // panned by x, quieter further out, following the waves of the picture.
  TILES.forEach((tile, i) => {
    const row = Math.round((tile.y - 40) / 200); // 0 (top) … 5
    const octave = row <= 1 ? 2 : row <= 3 ? 1 : 0;
    const note = PENTA[(i * 3 + row) % 5] + 12 * octave + 12;
    const voice = i % 3 === 0 ? glass(midiHz(note), 0.7) : marimba(midiHz(note), 0.7);
    put(tileAppearAt(tile) + 0.05, voice, 0.2 / (1 + tile.d * 0.35), pan(tile.x), 0.45);
  });
  // Rising bed into the logo, then a sparkle as it lands (the chord itself is in the score).
  const rise = new Float32Array(Math.ceil((END.icon - END.gather[0] + 0.2) * SR));
  {
    const nz = noiseGen(77);
    const bp = biquad("bp", 300, 0.9);
    for (let i = 0; i < rise.length; i++) {
      const x = i / rise.length;
      if (i % 32 === 0) bp.set(250 * Math.pow(16, x));
      rise[i] = (bp(nz()) * 0.8 + Math.sin((TAU * midiHz(62) * i) / SR) * 0.3) * Math.pow(x, 2) * (x > 0.95 ? (1 - x) * 20 : 1);
    }
  }
  put(END.gather[0], rise, 0.3, 0, 0.4);
  [86, 90, 93].forEach((m, i) => put(END.icon + i * 0.06, bell(midiHz(m), 2.5, 0.5), 0.12, -0.2 + i * 0.2, 0.9));

  // Small room.
  const wet = reverb(send, { room: 0.45, damp: 0.55, predelay: 0.008 });
  dry.addStereo(0, wet, 0.6);
  // Gentle top end.
  for (const ch of [dry.L, dry.R]) filterBuf(ch, "lp", 9000, 0.6);
  return dry;
}
