// Pure tuning-window maths (HANDOFF §6.1, Frost-Tune.dc.html).
import { FREQ_MAX, FREQ_MIN, STATIONS, type Station } from "./stations";

export const PX_PER_MHZ = 38.75;
export const LOCK_RANGE = 0.15;
export const BETWEEN_THRESHOLD = 0.3;
export const TICK_BASELINE = 52;

const r2 = (n: number) => Math.round(n * 100) / 100;

export function clampFreq(freq: number): number {
  return Math.min(FREQ_MAX, Math.max(FREQ_MIN, freq));
}

/** Screen x of a frequency in a window centred on `center`. */
export function freqToX(freq: number, center: number, width: number): number {
  return (freq - center) * PX_PER_MHZ + width / 2;
}

/** Dragging the scale right by dx lowers the frequency under the pointer. */
export function freqAfterDrag(start: number, dxPx: number): number {
  return clampFreq(start - dxPx / PX_PER_MHZ);
}

export function nearestStation(freq: number): { station: Station; distance: number } {
  let best = STATIONS[0];
  let distance = Infinity;
  for (const station of STATIONS) {
    const d = Math.abs(station.freq - freq);
    if (d < distance) {
      best = station;
      distance = d;
    }
  }
  return { station: best, distance };
}

export type TunerReading = {
  station: Station;
  distance: number;
  locked: boolean;
  between: boolean;
  /** Lit signal bars, 1..5. */
  bars: number;
  /** Static noise layer opacity, 0..1 (only between stations). */
  noise: number;
};

export function readTuner(freq: number): TunerReading {
  const { station, distance } = nearestStation(freq);
  const locked = distance <= LOCK_RANGE + 1e-9;
  const between = distance > BETWEEN_THRESHOLD + 1e-9;
  const bars = locked ? 5 : between ? 1 : 3;
  const noise = between ? Math.min(1, (distance - BETWEEN_THRESHOLD) / 1.2 + 0.35) : 0;
  return { station, distance, locked, between, bars, noise };
}

/**
 * Where a released fling settles: project the velocity (MHz/ms) forward with
 * exponential decay, then snap to the nearest station. Always a station.
 */
export function snapTarget(freq: number, velocityMhzPerMs = 0, decayMs = 325): number {
  const projected = clampFreq(freq + velocityMhzPerMs * decayMs);
  return nearestStation(projected).station.freq;
}

export function stepStation(freq: number, direction: 1 | -1): Station {
  const { station, distance } = nearestStation(freq);
  const index = STATIONS.indexOf(station);
  if (distance > LOCK_RANGE) {
    // Off-station: move to the neighbour in the requested direction.
    const candidates = STATIONS.filter((item) => direction > 0 ? item.freq > freq : item.freq < freq);
    return (direction > 0 ? candidates[0] : candidates.at(-1)) ?? station;
  }
  return STATIONS[Math.min(STATIONS.length - 1, Math.max(0, index + direction))];
}

export type TickGeometry = {
  minor: string;
  major: string;
  numbers: Array<{ x: number; label: string }>;
};

/** Ticks every 0.2 MHz bottom-aligned at y=52: integer 18, half 12, other 7. */
export function tickGeometry(center: number, width: number): TickGeometry {
  const lo = center - width / 2 / PX_PER_MHZ;
  const hi = center + width / 2 / PX_PER_MHZ;
  let minor = "";
  let major = "";
  const numbers: TickGeometry["numbers"] = [];
  for (let i = Math.ceil(lo * 5); i <= Math.floor(hi * 5); i += 1) {
    const f = i / 5;
    if (f < FREQ_MIN - 1e-9 || f > FREQ_MAX + 1e-9) continue;
    const x = r2((f - lo) * PX_PER_MHZ);
    const isInt = i % 5 === 0;
    const isHalf = !isInt && Math.abs(f * 2 - Math.round(f * 2)) < 0.001;
    const h = isInt ? 18 : isHalf ? 12 : 7;
    const seg = "M" + x + " " + (TICK_BASELINE - h) + "V" + TICK_BASELINE;
    if (isInt) {
      major += seg;
      if (i % 10 === 0) numbers.push({ x, label: String(Math.round(f)) });
    } else {
      minor += seg;
    }
  }
  return { minor, major, numbers };
}

export const KNURL_MAX_ANGLE = (70 * Math.PI) / 180;
export const KNURL_LINES = 31;

/**
 * Knurled dial: lines evenly spaced in angle within ±70°, projected onto the
 * cylinder (x = centre + R·sin a / sin 70°). `phase` (radians) rotates the
 * cylinder so the grooves travel while dragging.
 */
export function knurlXs(width: number, phase = 0): number[] {
  const step = (2 * KNURL_MAX_ANGLE) / (KNURL_LINES - 1);
  const radius = width / 2 - 7;
  const offset = ((phase % step) + step) % step;
  const xs: number[] = [];
  for (let k = -1; k <= KNURL_LINES; k += 1) {
    const a = -KNURL_MAX_ANGLE + step * k + offset;
    if (a < -KNURL_MAX_ANGLE - 1e-9 || a > KNURL_MAX_ANGLE + 1e-9) continue;
    xs.push(r2(width / 2 + (radius * Math.sin(a)) / Math.sin(KNURL_MAX_ANGLE)));
  }
  return xs;
}

export function knurlPath(width: number, phase = 0): string {
  return knurlXs(width, phase).map((x) => "M" + x + " 7V19").join("");
}

/** Radians of dial rotation per MHz tuned, so the grooves follow the drag. */
export function knurlPhaseForFreq(freq: number, width: number): number {
  const radius = width / 2 - 7;
  // Arc length equals pointer travel at the centre of the cylinder.
  return ((freq - FREQ_MIN) * PX_PER_MHZ * Math.sin(KNURL_MAX_ANGLE)) / Math.max(1, radius);
}

function rng(seed: number) {
  let a = seed >>> 0;
  return function next() {
    a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Static between-stations noise dots (deterministic). */
export function noisePath(width: number, height = 96, count = 260, seed = 7): string {
  const R = rng(seed);
  let d = "";
  for (let k = 0; k < count; k += 1) {
    const x = R() * width;
    const y = R() * height;
    const rr = 0.4 + R() * 0.6;
    d += "M" + r2(x - rr) + " " + r2(y) + "a" + r2(rr) + " " + r2(rr) + " 0 1 0 " + r2(2 * rr) + " 0a" + r2(rr) + " " + r2(rr) + " 0 1 0 " + r2(-2 * rr) + " 0Z";
  }
  return d;
}

/**
 * Tuning-in waveform: static noise fading into a clean sine as preparation
 * progresses (0 = all noise, 1 = smooth sine).
 */
export function waveformPath(progress: number, seed: number, width = 300, mid = 28): string {
  const p = Math.min(1, Math.max(0, progress));
  const R = rng(seed);
  let d = "";
  for (let x = 0; x <= width; x += 2) {
    const t = x / width;
    const noiseAmp = 20 * (1 - p) * Math.pow(1 - t * p, 1.6);
    const sineAmp = 12 * (0.25 + 0.75 * p) * Math.pow(Math.max(t, p * 0.6), 0.7);
    const y = mid + (R() * 2 - 1) * noiseAmp + sineAmp * Math.sin(x * 0.12);
    d += (x ? "L" : "M") + x + " " + r2(y);
  }
  return d;
}
