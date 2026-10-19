// Pure tuning-window maths (HANDOFF §6.1, Frost-Tune.dc.html).
import { FREQ_MAX, FREQ_MIN, STATIONS, type Station } from "./stations";

/**
 * Pixels of dial travel per MHz. Stations sit about 4.3 MHz apart, so about 120px of drag moves from one to the next,
 * and the dial window (about 320px wide) shows a station and a whole neighbour on each side (wider and the
 * neighbours' names run into the window's edge).
 */
export const PX_PER_MHZ = 28;
export const LOCK_RANGE = 0.15;
export const BETWEEN_THRESHOLD = 0.3;
export const TICK_BASELINE = 56;
/** Height of the dial window, and of its scale layer. */
export const DIAL_HEIGHT = 64;

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
  const noise = noiseForDistance(distance);
  return { station, distance, locked, between, noise };
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

/** The whole band drawn once (ticks only), for a translateX-only layer. */
export function fullScaleGeometry(): TickGeometry {
  return tickGeometry((FREQ_MIN + FREQ_MAX) / 2, FULL_SCALE_WIDTH);
}

export type TickGeometry = {
  minor: string;
  major: string;
};

/** Ticks every 0.2 MHz bottom-aligned at TICK_BASELINE: integer 16, half 10, other 6. */
export function tickGeometry(center: number, width: number): TickGeometry {
  const lo = center - width / 2 / PX_PER_MHZ;
  const hi = center + width / 2 / PX_PER_MHZ;
  let minor = "";
  let major = "";
  for (let i = Math.ceil(lo * 5); i <= Math.floor(hi * 5); i += 1) {
    const f = i / 5;
    if (f < FREQ_MIN - 1e-9 || f > FREQ_MAX + 1e-9) continue;
    const x = r2((f - lo) * PX_PER_MHZ);
    const isInt = i % 5 === 0;
    const isHalf = !isInt && Math.abs(f * 2 - Math.round(f * 2)) < 0.001;
    const h = isInt ? 16 : isHalf ? 10 : 6;
    const seg = "M" + x + " " + (TICK_BASELINE - h) + "V" + TICK_BASELINE;
    if (isInt) major += seg;
    else minor += seg;
  }
  return { minor, major };
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
export function noisePath(width: number, height = DIAL_HEIGHT, count = 200, seed = 7): string {
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

/** Milliseconds of wheel silence before the dial snaps to the nearest station. */
export const WHEEL_SNAP_DELAY_MS = 150;

/**
 * Wheel/trackpad scroll as scale travel in px: the dominant axis wins, line
 * and page modes are normalised. Down/right scrolls toward higher frequencies.
 */
export function wheelDeltaPx(
  event: { deltaX: number; deltaY: number; deltaMode: number },
  pageWidth = 310,
): number {
  const delta = Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY;
  if (!Number.isFinite(delta)) return 0;
  if (event.deltaMode === 1) return delta * 16;
  if (event.deltaMode === 2) return delta * pageWidth;
  return delta;
}

/**
 * How far (MHz) the tuner is from a station before its picture has left and its words have faded: half the usual
 * spacing, so that at the half-way point between two stations neither is showing (and the card carries static).
 */
export const STATION_FADE_MHZ = 2.15;

export type StationBlend = {
  station: Station;
  /** MHz from the dial's frequency, whichever side it is on. */
  distance: number;
  /** 1 on the station, 0 once `STATION_FADE_MHZ` away: opacity of its words. */
  weight: number;
  /** 0 on the station, 1 once `STATION_FADE_MHZ` away: how far its picture has flown off. */
  away: number;
};

/** Every station's share of the card at this frequency; depends on the distance only, so dragging back replays it. */
export function stationBlends(freq: number): StationBlend[] {
  return STATIONS.map((station) => {
    const distance = Math.abs(station.freq - freq);
    const away = Math.min(1, distance / STATION_FADE_MHZ);
    return { station, distance, weight: 1 - away, away };
  });
}

/**
 * The card's tint is the nearest station's, with the second nearest laid over it at `amount` (0 on a station,
 * 0.5 half-way): the same colour from either side of the half-way point.
 */
export function tintBlend(freq: number): { base: Station; over: Station; amount: number } {
  const ranked = [...STATIONS].sort((a, b) => Math.abs(a.freq - freq) - Math.abs(b.freq - freq));
  const [base, over] = ranked;
  const near = Math.abs(base.freq - freq);
  const far = Math.abs(over.freq - freq);
  return { base, over, amount: near + far === 0 ? 0 : near / (near + far) };
}

/** Where the poster is as it flies off (away 1) and back (away 0): right and a little up, turning and growing. */
export function posterPose(away: number): { x: number; y: number; rotate: number; scale: number } {
  const eased = Math.pow(Math.min(1, Math.max(0, away)), 2.2);
  return { x: eased * 300, y: -eased * 70, rotate: 6 + eased * 10, scale: 1 + eased * 0.1 };
}

/**
 * Static over the card's picture: none on a station, strongest half-way between two (as the picture has gone and
 * the next has not arrived), so that tuning past a station reads as passing through the band.
 */
export function cardNoise(distance: number): number {
  const t = Math.min(1, Math.max(0, (distance - 0.9) / (STATION_FADE_MHZ - 0.9)));
  return 0.7 * t * t * (3 - 2 * t);
}

/** The station after `fromFreq` in a direction (1 = higher, -1 = lower), or null at the end of the band. */
export function neighbourStation(fromFreq: number, direction: 1 | -1): Station | null {
  const epsilon = 1e-6;
  if (direction > 0) return STATIONS.find((station) => station.freq > fromFreq + epsilon) ?? null;
  return [...STATIONS].reverse().find((station) => station.freq < fromFreq - epsilon) ?? null;
}
