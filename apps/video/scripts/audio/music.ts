// Original score in D major pentatonic (D E F# A B), built on one 4-bar motif.
// Sections follow the film: morning (100 BPM, City-Pop-ish e-piano), afternoon
// (86 BPM lo-fi, muffled during the breakdown), rainy night (66 BPM, sparse,
// ducked under the host), next day + ending (the morning motif returns, grows
// with the cover wall and lands on Dmaj9 with the logo). No music in the cold open.
import { AFTERNOON, DURATION, END, NIGHT } from "../../src/timeline";
import { eo, p } from "../../src/lib/math";
import { bass, bell, epiano, hat, kick, marimba, midiHz, pad, reverb, snare, Stereo, sweepLowpass } from "./dsp";

/** [beat, midi, beats] — the film's motif (4 bars of 4/4). */
export const MOTIF: Array<[number, number, number]> = [
  [0, 69, 1], [1, 66, 0.5], [1.5, 64, 0.5], [2, 62, 2],
  [4, 64, 1], [5, 66, 1], [6, 69, 2],
  [8, 71, 1], [9, 69, 0.5], [9.5, 66, 0.5], [10, 69, 1], [11, 74, 1],
  [12, 71, 1.5], [13.5, 69, 0.5], [14, 66, 2],
];

type Chord = { bass: number; notes: number[] };
const DMAJ9: Chord = { bass: 38, notes: [54, 57, 61, 64] };
const BM11: Chord = { bass: 35, notes: [57, 62, 64, 66] };
const GMAJ9: Chord = { bass: 43, notes: [59, 62, 66, 69] };
const A6SUS: Chord = { bass: 45, notes: [59, 62, 64, 69] };
const DMAJ9_F: Chord = { bass: 42, notes: [57, 61, 64, 66] };
const BRIGHT = [DMAJ9, BM11, GMAJ9, A6SUS];
const JAZZ = [BM11, GMAJ9, DMAJ9_F, A6SUS];

const MUSIC_LEN = DURATION + 3;

class Section {
  dry: Stereo;
  wet: Stereo; // reverb send
  constructor(public start: number, public bpm: number, len = MUSIC_LEN) {
    this.dry = new Stereo(len);
    this.wet = new Stereo(len);
  }
  t(beat: number) {
    return this.start + (beat * 60) / this.bpm;
  }
  beats(b: number) {
    return (b * 60) / this.bpm;
  }
  note(beat: number, x: Float32Array, gain: number, pan = 0, send = 0.2) {
    const at = this.t(beat);
    this.dry.addMono(at, x, gain, pan);
    if (send > 0) this.wet.addMono(at, x, gain * send, pan);
  }
}

function comp(s: Section, bar: number, c: Chord, pattern: Array<[number, number, number]>, gain: number, bright = 1) {
  for (const [b, dur, vel] of pattern) {
    c.notes.forEach((m, k) => s.note(bar * 4 + b + k * 0.012, epiano(midiHz(m), s.beats(dur), vel, bright), gain, -0.25 + k * 0.17, 0.25));
  }
}

function motif(s: Section, startBeat: number, voice: (f: number, beats: number) => Float32Array, gain: number, transpose = 0, stretch = 1, pan = 0.1, send = 0.3) {
  for (const [b, m, d] of MOTIF) s.note(startBeat + b * stretch, voice(midiHz(m + transpose), d * stretch), gain, pan, send);
}

/** 0:09–0:33 morning: bright e-piano, light groove, ~100 BPM. */
function morning() {
  const s = new Section(9.0, 100);
  for (let bar = 0; bar < 11; bar++) {
    const c = BRIGHT[bar % 4];
    comp(s, bar, c, [[0, 1, 0.65], [1.5, 0.5, 0.45], [2.5, 0.5, 0.5], [3.5, 0.5, 0.4]], 0.16, 1.1);
    [[0, c.bass, 0.75], [1.5, c.bass + 7, 0.5], [2, c.bass, 0.5], [3, c.bass + 12, 0.45], [3.5, c.bass + 7, 0.45]].forEach(([b, m, d]) =>
      s.note(bar * 4 + b, bass(midiHz(m), s.beats(d), 0.7), 0.32, 0, 0),
    );
    if (bar >= 1) {
      [0, 2, 2.75].forEach((b) => s.note(bar * 4 + b, kick(b === 2.75 ? 0.5 : 0.8), 0.32, 0, 0));
      [1, 3].forEach((b) => s.note(bar * 4 + b, snare(900 + bar * 7 + b, 0.45, 2000, 0.06), 0.14, -0.1, 0.15));
      for (let h = 0; h < 8; h++) s.note(bar * 4 + h * 0.5, hat(1300 + bar * 13 + h, h % 2 ? 0.28 : 0.4), 0.11, 0.35, 0);
    }
  }
  // The motif (an octave up) twice, after the chapter card.
  const lead = (f: number, beats: number) => epiano(f * 2, s.beats(beats), 0.75, 1.3);
  motif(s, 8, lead, 0.15, 0, 1, 0.15);
  motif(s, 24, lead, 0.15, 0, 1, 0.15);
  return s;
}

/** 0:33–1:05 afternoon: lo-fi, ~86 BPM, swung, jazz chords. */
function afternoon() {
  const s = new Section(33.0, 86);
  const sw = (b: number) => (b % 1 === 0.5 ? b + 0.16 : b); // swing the off-beats
  for (let bar = 0; bar < 12; bar++) {
    const c = JAZZ[bar % 4];
    comp(s, bar, c, [[0, 2, 0.55], [sw(2.5), 1.3, 0.45]], 0.17, 0.7);
    s.note(bar * 4, bass(midiHz(c.bass), s.beats(1.6), 0.7), 0.34, 0, 0);
    s.note(bar * 4 + sw(2.5), bass(midiHz(c.bass + 7), s.beats(1), 0.55), 0.3, 0, 0);
    [0, sw(1.5), 2.5].forEach((b, k) => s.note(bar * 4 + b, kick(k === 1 ? 0.55 : 0.8), 0.3, 0, 0));
    [1, 3].forEach((b) => s.note(bar * 4 + b, snare(4100 + bar * 3 + b, 0.5, 1300, 0.12), 0.15, 0.05, 0.2));
    for (let h = 0; h < 8; h++) s.note(bar * 4 + sw(h * 0.5), hat(4700 + bar * 11 + h, h % 2 ? 0.22 : 0.34, 0.05), 0.1, 0.3, 0);
  }
  // Motif on marimba, half-time feel, before the breakdown and again after.
  const mar = (f: number) => marimba(f, 0.8);
  motif(s, 4, mar, 0.13, 0, 1, 0.2, 0.25);
  motif(s, 32, mar, 0.13, 0, 1, 0.2, 0.25);
  // Lo-fi tone; the breakdown muffles everything, the player opens it again.
  const [b0] = AFTERNOON.breakdown;
  const open = AFTERNOON.player;
  const cutoff = (t: number) => {
    const shut = eo(p(t, b0, b0 + 0.8)) * (1 - eo(p(t, open - 0.2, open + 0.6)));
    return Math.exp(Math.log(4200) * (1 - shut) + Math.log(480) * shut);
  };
  sweepLowpass(s.dry, cutoff);
  sweepLowpass(s.wet, cutoff);
  return s;
}

/** 1:05–1:40 rainy night: sparse e-piano and pad, ~66 BPM, long reverb, ducked under the host. */
function night() {
  const s = new Section(65.0, 66);
  const prog = [DMAJ9, BM11, GMAJ9, A6SUS, DMAJ9];
  prog.forEach((c, k) => {
    c.notes.forEach((m, j) => s.note(k * 8 + j * 0.02, pad(midiHz(m), s.beats(8), 1.6, 2.2, 1400), 0.07, -0.3 + j * 0.2, 0.6));
    s.note(k * 8, bass(midiHz(c.bass), s.beats(6), 0.5), 0.22, 0, 0.2);
    // A few soft e-piano chord tones.
    [0, 3, 5.5].forEach((b, i) => s.note(k * 8 + b, epiano(midiHz(c.notes[(i + k) % 4] + 12), s.beats(2.5), 0.45, 0.6), 0.12, -0.2 + i * 0.2, 0.7));
  });
  // The motif, slowed to half speed, in fragments.
  const ep = (f: number, beats: number) => epiano(f, s.beats(beats), 0.5, 0.7);
  MOTIF.slice(0, 7).forEach(([b, m, d]) => s.note(16 + b * 1.5, ep(midiHz(m + 12), d * 1.5), 0.12, 0.15, 0.8));
  // Duck ~10 dB in step with the mixer panel (NightOverlay.tsx).
  const [h0, h1] = NIGHT.host;
  const duck = (t: number) => 1 - 0.684 * eo(p(t, h0 - 0.1, h0 + 0.5)) * (1 - eo(p(t, h1, h1 + 0.6)));
  s.dry.shape(duck);
  s.wet.shape(duck);
  return s;
}

/** 1:40–2:08: the morning motif returns, fills out with the wall, lands on Dmaj9 with the logo. */
function finale() {
  const land = END.icon; // 1:58.8
  const s = new Section(land - 8 * 2.4, 100); // bar 8 downbeat = the logo
  const lead = (f: number, beats: number) => epiano(f * 2, s.beats(beats), 0.7, 1.2);
  for (let bar = 0; bar < 8; bar++) {
    const c = BRIGHT[bar % 4];
    c.notes.forEach((m, j) => s.note(bar * 4, pad(midiHz(m), s.beats(4), 0.6, 0.9, 1200 + bar * 250), 0.03 + bar * 0.007, -0.3 + j * 0.2, 0.5));
    if (bar >= 2) [[0, c.bass, 1.5], [2, c.bass + 7, 1], [3, c.bass + 12, 0.8]].forEach(([b, m, d]) => s.note(bar * 4 + b, bass(midiHz(m), s.beats(d), 0.6), 0.28, 0, 0));
    if (bar >= 2 && bar < 7) for (let h = 0; h < 8; h++) s.note(bar * 4 + h * 0.5, hat(7000 + bar * 17 + h, h % 2 ? 0.2 : 0.32), 0.09, 0.3, 0);
    if (bar >= 4 && bar < 7) {
      [0, 2].forEach((b) => s.note(bar * 4 + b, kick(0.7), 0.26, 0, 0));
      [1, 3].forEach((b) => s.note(bar * 4 + b, snare(7300 + bar * 5 + b, 0.4, 2000, 0.06), 0.11, -0.1, 0.2));
      comp(s, bar, c, [[0, 1, 0.55], [1.5, 0.5, 0.4], [2.5, 0.5, 0.45], [3.5, 0.5, 0.38]], 0.12, 1.1);
    }
  }
  motif(s, 0, lead, 0.13, 0, 1, 0.1, 0.35);
  motif(s, 16, lead, 0.14, 0, 1, 0.1, 0.35);
  motif(s, 16, (f) => marimba(f * 2, 0.7), 0.08, 0, 1, -0.25, 0.35);
  // Landing chord: Dmaj9 on pad, e-piano and bell, with a long tail.
  const chord = [50, 57, 61, 64, 66, 69];
  chord.forEach((m, j) => {
    s.note(32 + j * 0.03, pad(midiHz(m), 4.5, 0.05, 3.5, 2200), 0.07, -0.4 + j * 0.16, 0.9);
    s.note(32 + j * 0.04, epiano(midiHz(m + 12), 2.5, 0.55, 0.9), 0.1, -0.4 + j * 0.16, 0.9);
  });
  s.note(32, bass(midiHz(38), 5, 0.7), 0.3, 0, 0.3);
  s.note(32, bell(midiHz(81), 3, 0.6), 0.06, 0.2, 1);
  return s;
}

function xfade(t: number, a: number, b: number, w = 1) {
  return eo(p(t, a - w / 2, a + w / 2)) * (1 - eo(p(t, b - w / 2, b + w / 2)));
}

export function buildMusic() {
  const out = new Stereo(MUSIC_LEN);
  const parts: Array<[Section, number, number, { room: number; damp: number; wet: number }]> = [
    [morning(), 9.0, 33.0, { room: 0.55, damp: 0.5, wet: 0.5 }],
    [afternoon(), 33.0, 65.0, { room: 0.6, damp: 0.6, wet: 0.5 }],
    [night(), 65.0, 100.0, { room: 0.92, damp: 0.35, wet: 1.0 }],
    [finale(), 100.0, DURATION + 2, { room: 0.9, damp: 0.35, wet: 0.9 }],
  ];
  for (const [s, a, b, rv] of parts) {
    const wet = reverb(s.wet, { room: rv.room, damp: rv.damp, predelay: 0.02 });
    const sec = new Stereo(MUSIC_LEN);
    sec.addStereo(0, s.dry);
    sec.addStereo(0, wet, rv.wet);
    sec.shape((t) => xfade(t, a, b));
    out.addStereo(0, sec);
  }
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
