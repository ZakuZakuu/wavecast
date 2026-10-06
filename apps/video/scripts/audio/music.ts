// Original score: floating, lazy jazz harmony (maj7, m9, 11, 13, sus; open
// voicings), slow 16th swing with dragged snare and brushes, mellow e-piano,
// round sine bass, tape warmth and a faint vinyl bed, in D major. No lead
// melody: the harmony carries it. Progressions are original. No music in the cold open.
import { AFTERNOON, DURATION, END, NIGHT } from "../../src/timeline";
import { eo, p, rng } from "../../src/lib/math";
import { bell, biquad, epiano, filterBuf, midiHz, noiseGen, pad, reverb, SR, Stereo, sweepLowpass } from "./dsp";
import { arpNote, brush, brushSnare, keys, roundBass, softKick } from "./voices";

/** [beat, midi, beats] — the film's motif (4 bars of 4/4). */
export const MOTIF: Array<[number, number, number]> = [
  [0, 69, 1], [1, 66, 0.5], [1.5, 64, 0.5], [2, 62, 2],
  [4, 64, 1], [5, 66, 1], [6, 69, 2],
  [8, 71, 1], [9, 69, 0.5], [9.5, 66, 0.5], [10, 69, 1], [11, 74, 1],
  [12, 71, 1.5], [13.5, 69, 0.5], [14, 66, 2],
];

type Chord = { bass: number; notes: number[] };
// Open voicings in the middle register; roots mostly left to the bass.
const C = {
  // morning / finale: Gmaj9 → F#m11 → Em9 → A13sus4
  Gmaj9: { bass: 43, notes: [59, 62, 66, 69] },
  Fsm11: { bass: 42, notes: [57, 61, 64, 71] },
  Em9: { bass: 40, notes: [55, 59, 62, 66] },
  A13sus4: { bass: 45, notes: [55, 62, 66, 71] },
  // afternoon: Bm9 → E13 → Amaj9 → Dmaj9
  Bm9: { bass: 35, notes: [57, 61, 62, 66] },
  E13: { bass: 40, notes: [56, 61, 62, 66] },
  Amaj9: { bass: 45, notes: [56, 59, 61, 64] },
  Dmaj9: { bass: 38, notes: [54, 57, 61, 64] },
  // night: Gmaj7#11 → F#m7 → Em9 → A7sus4
  Gmaj7s11: { bass: 43, notes: [59, 61, 62, 66] },
  Fsm7: { bass: 42, notes: [57, 61, 64, 69] },
  A7sus4: { bass: 45, notes: [55, 62, 64, 69] },
} satisfies Record<string, Chord>;
const MORNING_PROG = [C.Gmaj9, C.Fsm11, C.Em9, C.A13sus4];
const AFTERNOON_PROG = [C.Bm9, C.E13, C.Amaj9, C.Dmaj9];
const NIGHT_PROG = [C.Gmaj7s11, C.Fsm7, C.Em9, C.A7sus4];

const MUSIC_LEN = DURATION + 3;
const SWING = 0.58; // 16th-note swing
const DRAG = 0.025; // snare and hats sit ~25 ms behind the beat

/** Swing the off-beat 16ths. */
const sw = (b: number) => (Math.round(b * 4) % 2 === 1 ? b + (SWING - 0.5) * 0.5 : b);

class Section {
  dry: Stereo;
  wet: Stereo; // reverb send
  drums: Stereo; // kept out of the sidechain
  kicks: number[] = [];
  constructor(public start: number, public bpm: number, len = MUSIC_LEN) {
    this.dry = new Stereo(len);
    this.wet = new Stereo(len);
    this.drums = new Stereo(len);
  }
  t(beat: number) {
    return this.start + (beat * 60) / this.bpm;
  }
  beats(b: number) {
    return (b * 60) / this.bpm;
  }
  note(beat: number, x: Float32Array, gain: number, pan = 0, send = 0.2, late = 0) {
    const at = this.t(beat) + late;
    this.dry.addMono(at, x, gain, pan);
    if (send > 0) this.wet.addMono(at, x, gain * send, pan);
  }
  /** Stereo e-piano note: the detuned pair is spread around `pan`. */
  key(beat: number, m: number, beatsLong: number, vel: number, gain: number, pan = 0, send = 0.35) {
    const [l, r] = keys(midiHz(m), this.beats(beatsLong), vel);
    const at = this.t(beat);
    for (const [x, p] of [[l, pan - 0.35], [r, pan + 0.35]] as const) {
      this.dry.addMono(at, x, gain * 0.7, p);
      this.wet.addMono(at, x, gain * 0.7 * send, p);
    }
  }
  kick(beat: number, vel = 0.7, gain = 0.32) {
    this.kicks.push(this.t(beat));
    this.drums.addMono(this.t(beat), softKick(vel), gain, 0);
  }
  drum(beat: number, x: Float32Array, gain: number, pan = 0) {
    this.drums.addMono(this.t(beat) + DRAG, x, gain, pan);
  }
  /** Light sidechain: everything but the drums dips ~2 dB under each kick and breathes back. */
  sidechain() {
    const ks = this.kicks.slice().sort((a, b) => a - b);
    let k = 0;
    const g = (t: number) => {
      while (k + 1 < ks.length && ks[k + 1] <= t) k++;
      const d = t - ks[k];
      if (!ks.length || d < 0) return 1;
      return 1 - 0.22 * Math.min(1, d / 0.006) * Math.exp(-d / 0.16);
    };
    this.dry.shape(g);
    k = 0;
    this.wet.shape(g);
  }
}

/** Chord stab / held chord on the e-piano, slightly rolled. */
function chord(s: Section, beat: number, c: Chord, beatsLong: number, vel: number, gain: number, roll = 0.015) {
  c.notes.forEach((m, k) => s.key(beat + k * roll * (s.bpm / 60), m, beatsLong, vel * (0.9 + 0.05 * k), gain, -0.3 + k * 0.2));
}

function bassLine(s: Section, bar: number, c: Chord, pattern: Array<[number, number, number, number?]>, gain = 0.34) {
  for (const [b, interval, d, slide] of pattern) s.note(bar * 4 + sw(b), roundBass(midiHz(c.bass + interval), s.beats(d), 0.75, slide ?? 0), gain, 0, 0);
}

function lazyDrums(s: Section, bar: number, level: number, seed: number) {
  s.kick(bar * 4, 0.7 * level);
  s.kick(bar * 4 + sw(2.75), 0.45 * level);
  s.drum(bar * 4 + 1, brushSnare(seed + 1, 0.5 * level), 0.2, -0.05);
  s.drum(bar * 4 + 3, brushSnare(seed + 3, 0.55 * level), 0.2, -0.05);
  for (let h = 0; h < 16; h++) {
    const b = h * 0.25;
    if (h % 2 === 1 && h % 4 !== 3) continue; // a loose 16th pattern, not every step
    s.drum(bar * 4 + sw(b), brush(seed + 10 + h, (h % 4 === 0 ? 0.42 : 0.26) * level), 0.13, 0.3);
  }
}

/** 0:09–0:33 morning: lazy morning jazz, ~82 BPM, e-piano leads, drums barely there. */
function morning() {
  const s = new Section(9.0, 82);
  for (let bar = 0; bar < 9; bar++) {
    const c = MORNING_PROG[bar % 4];
    chord(s, bar * 4, c, 2.6, 0.55, 0.15);
    chord(s, bar * 4 + sw(2.75), c, 1.0, 0.38, 0.1, 0.01);
    if (bar >= 1) bassLine(s, bar, c, [[0, 0, 1.6], [sw(1.75), 7, 0.5], [2.5, 12, 1.2, bar % 2 ? 2 : 0]], 0.3);
    if (bar >= 2) lazyDrums(s, bar, 0.6, 2000 + bar * 31);
  }
  s.sidechain();
  return s;
}

/** 0:33–1:05 afternoon: dragged jazz-hop, ~88 BPM; muffled during the breakdown. */
function afternoon() {
  const s = new Section(33.0, 88);
  for (let bar = 0; bar < 12; bar++) {
    const c = AFTERNOON_PROG[bar % 4];
    chord(s, bar * 4, c, 1.6, 0.55, 0.15);
    chord(s, bar * 4 + sw(1.75), c, 0.5, 0.35, 0.08, 0.008);
    chord(s, bar * 4 + sw(2.5), c, 1.3, 0.45, 0.12);
    bassLine(s, bar, c, [[0, 0, 1.4], [sw(1.5), 0, 0.4], [sw(2.25), 7, 0.6], [3.5, 10, 0.4, 2]]);
    lazyDrums(s, bar, 0.9, 5000 + bar * 37);
  }
  s.sidechain();
  const [b0] = AFTERNOON.breakdown;
  const open = AFTERNOON.player;
  const cutoff = (t: number) => {
    const shut = eo(p(t, b0, b0 + 0.8)) * (1 - eo(p(t, open - 0.2, open + 0.6)));
    return Math.exp(Math.log(9000) * (1 - shut) + Math.log(480) * shut);
  };
  for (const b of [s.dry, s.wet, s.drums]) sweepLowpass(b, cutoff);
  return s;
}

/** 1:05–1:40 rainy night: floating, rubato, ~66 BPM, long reverb; ducked under the host. */
function night() {
  const s = new Section(65.0, 66);
  const R = rng(6606);
  for (let bar = 0; bar < 10; bar++) {
    const c = NIGHT_PROG[Math.floor(bar / 2) % 4];
    if (bar % 2 === 0) {
      c.notes.forEach((m, j) => s.note(bar * 4 + j * 0.02, pad(midiHz(m), s.beats(8), 1.8, 2.5, 1300), 0.06, -0.3 + j * 0.2, 0.7));
      s.note(bar * 4, roundBass(midiHz(c.bass), s.beats(6), 0.55, R() < 0.4 ? 2 : 0), 0.24, 0, 0.15);
    }
    // Free, slightly rolled e-piano arpeggios that drift around the beat.
    const shape = [0, 1, 2, 3, 2].slice(0, 3 + Math.floor(R() * 3));
    shape.forEach((k, i) => s.key(bar * 4 + 0.5 + i * (0.6 + R() * 0.5), c.notes[k] + 12, 2.2, 0.42, 0.1, -0.3 + k * 0.2, 0.8));
  }
  const [h0, h1] = NIGHT.host;
  const duck = (t: number) => 1 - 0.684 * eo(p(t, h0 - 0.1, h0 + 0.5)) * (1 - eo(p(t, h1, h1 + 0.6)));
  s.dry.shape(duck);
  s.wet.shape(duck);
  s.drums.shape(duck);
  return s;
}

/** 1:40–2:08: the new morning arrangement returns, fills out with arpeggios and pads over the wall, lands on Dmaj9 with the logo. */
function finale() {
  const land = END.icon;
  const bar = (60 / 82) * 4;
  const s = new Section(land - 8 * bar, 82); // bar 8 downbeat = the logo
  for (let b = 0; b < 8; b++) {
    const c = MORNING_PROG[b % 4];
    chord(s, b * 4, c, 2.6, 0.5, 0.14);
    if (b >= 3) bassLine(s, b, c, [[0, 0, 1.6], [sw(1.75), 7, 0.5], [2.5, 12, 1.2, b % 2 ? 2 : 0]], 0.28);
    if (b >= 4) {
      c.notes.forEach((m, j) => s.note(b * 4, pad(midiHz(m), s.beats(4), 0.8, 1, 1400 + b * 200), 0.03 + (b - 4) * 0.008, -0.3 + j * 0.2, 0.5));
      // 16th arpeggios through the chord tones, growing with the wall.
      for (let k = 0; k < 16; k++) {
        if (b === 4 && k % 2) continue;
        const m = c.notes[[0, 1, 2, 3, 2, 1][k % 6]] + 12;
        s.note(b * 4 + sw(k * 0.25), arpNote(midiHz(m), 0.5), 0.05 + (b - 4) * 0.012, -0.5 + (k % 6) * 0.2, 0.4);
      }
    }
    if (b >= 5 && b < 7) lazyDrums(s, b, 0.55, 9000 + b * 29);
  }
  // Landing chord: Dmaj9, open, long tail.
  const chordNotes = [50, 57, 61, 64, 66, 69];
  chordNotes.forEach((m, j) => {
    s.note(32 + j * 0.03, pad(midiHz(m), 4.5, 0.08, 3.5, 2000), 0.07, -0.4 + j * 0.16, 0.9);
    s.key(32 + j * 0.04, m + 12, 3, 0.5, 0.11, -0.4 + j * 0.16, 0.9);
  });
  s.note(32, roundBass(midiHz(38), 5, 0.7), 0.3, 0, 0.3);
  s.note(32, bell(midiHz(81), 3, 0.5), 0.05, 0.2, 1);
  s.sidechain();
  return s;
}

function xfade(t: number, a: number, b: number, w = 1) {
  return eo(p(t, a - w / 2, a + w / 2)) * (1 - eo(p(t, b - w / 2, b + w / 2)));
}

export function buildMusic() {
  const out = new Stereo(MUSIC_LEN);
  const parts: Array<[Section, number, number, { room: number; damp: number; wet: number }]> = [
    [morning(), 9.0, 33.0, { room: 0.75, damp: 0.55, wet: 0.6 }],
    [afternoon(), 33.0, 65.0, { room: 0.7, damp: 0.6, wet: 0.5 }],
    [night(), 65.0, 100.0, { room: 0.96, damp: 0.4, wet: 1.1 }],
    [finale(), 100.0, DURATION + 2, { room: 0.88, damp: 0.45, wet: 0.85 }],
  ];
  for (const [s, a, b, rv] of parts) {
    const wet = reverb(s.wet, { room: rv.room, damp: rv.damp, predelay: 0.02 });
    const sec = new Stereo(MUSIC_LEN);
    sec.addStereo(0, s.dry);
    sec.addStereo(0, wet, rv.wet);
    sec.addStereo(0, s.drums);
    sec.shape((t) => xfade(t, a, b));
    out.addStereo(0, sec);
  }
  // Tape: gentle saturation, highs rolled off above ~9 kHz, a faint vinyl bed.
  out.scale(0.5 / out.peak());
  const drive = 1.8;
  for (const ch of [out.L, out.R]) {
    for (let i = 0; i < ch.length; i++) ch[i] = Math.tanh(ch[i] * drive) / drive;
    filterBuf(ch, "lp", 9000, 0.5);
    filterBuf(ch, "lp", 11000, 0.5);
  }
  const vinyl = new Stereo(MUSIC_LEN);
  const R = rng(3303);
  for (const [ch, sd] of [[vinyl.L, 71], [vinyl.R, 72]] as const) {
    const nz = noiseGen(sd);
    const bp = biquad("bp", 1500, 0.4);
    let crackle = 0;
    for (let i = 0; i < ch.length; i++) {
      if (R() < 6 / SR) crackle = 0.5 + R();
      crackle *= 0.985;
      ch[i] = bp(nz()) * 0.004 + nz() * crackle * 0.012;
    }
  }
  vinyl.shape((t) => xfade(t, 9.0, DURATION + 2, 2));
  out.addStereo(0, vinyl);
  // Final fade with the picture (2:07–2:08).
  out.shape((t) => 1 - eo(p(t, END.fade[0] - 1.5, END.fade[1])));
  return out;
}

/** A short fragment of the motif for the cold-open "station" moments. */
export function motifFragment(startNote: number, notes = 3) {
  const s = new Section(0, 100, 2);
  const i0 = MOTIF.findIndex(([, m]) => m % 12 === startNote % 12);
  const pick = MOTIF.slice(Math.max(0, i0), Math.max(0, i0) + notes);
  const b0 = pick[0][0];
  pick.forEach(([b, m, d]) => s.note(b - b0, epiano(midiHz(m), s.beats(Math.min(d, 1)), 0.7, 1), 0.5, 0, 0));
  return s.dry;
}
