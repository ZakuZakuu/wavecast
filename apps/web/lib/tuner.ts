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
  /** Static noise opacity, 0..1, rising continuously with distance from a station. */
  noise: number;
};

/** Noise grows smoothly from the lock range to ~1.2 MHz away (no on/off steps). */
export function noiseForDistance(distance: number): number {
  const t = Math.min(1, Math.max(0, (distance - LOCK_RANGE) / (1.2 - LOCK_RANGE)));
  return t * t * (3 - 2 * t);
}

export function readTuner(freq: number): TunerReading {
  const { station, distance } = nearestStation(freq);
  const locked = distance <= LOCK_RANGE + 1e-9;
  const between = distance > BETWEEN_THRESHOLD + 1e-9;
  const bars = locked ? 5 : between ? 1 : 3;
  const noise = noiseForDistance(distance);
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

/** Width in px of the whole 87.5–108 MHz scale. */
export const FULL_SCALE_WIDTH = (FREQ_MAX - FREQ_MIN) * PX_PER_MHZ;

/** X of a frequency on the full scale layer (0 at 87.5 MHz). */
export function scaleX(freq: number): number {
  return (freq - FREQ_MIN) * PX_PER_MHZ;
}

/** translateX of the full scale so `freq` sits under the window's centre. */
export function scaleTranslate(freq: number, windowWidth: number): number {
  return windowWidth / 2 - scaleX(freq);
}

/** The whole band drawn once (ticks + numbers), for a translateX-only layer. */
export function fullScaleGeometry(): TickGeometry {
  return tickGeometry((FREQ_MIN + FREQ_MAX) / 2, FULL_SCALE_WIDTH);
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
