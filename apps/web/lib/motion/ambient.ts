// Continuous ambient motion for 开播中 (MOTION.md §4.8). Everything is a pure
// function of real elapsed time, so frames differ only slightly.

/** Damped pointer swing: A · e^(−t/τ) · sin(2πt/T), zero after `durationMs`. */
export function swingOffset(
  tMs: number,
  amplitude: number,
  tauMs = 250,
  periodMs = 300,
  durationMs = 900,
): number {
  if (tMs <= 0 || tMs >= durationMs) return 0;
  return amplitude * Math.exp(-tMs / tauMs) * Math.sin((2 * Math.PI * tMs) / periodMs);
}

// Four sines with different spatial frequencies whose phases drift slowly.
const NOISE_LAYERS = [
  { k: 0.11, w: 1.7, a: 0.42, p: 0.3 },
  { k: 0.23, w: -2.3, a: 0.28, p: 1.9 },
  { k: 0.37, w: 3.1, a: 0.18, p: 4.2 },
  { k: 0.61, w: -4.4, a: 0.12, p: 2.7 },
];

/** Smooth pseudo-noise in [-1, 1] over x (px) and time (s): continuous in both. */
export function smoothNoise(x: number, tSeconds: number): number {
  let value = 0;
  for (const layer of NOISE_LAYERS) {
    value += layer.a * Math.sin(layer.k * x + layer.w * tSeconds + layer.p);
  }
  return value;
}

export const SINE_SPEED = 2 * Math.PI * 0.8; // rad per second

/**
 * Waveform height at x: noise × (1 − clean) + sine × clean. `clean` runs from
 * 0 (static) to 1 (smooth sine).
 */
export function waveformY(x: number, tSeconds: number, clean: number, mid = 28, noiseAmp = 20, sineAmp = 12): number {
  const c = Math.min(1, Math.max(0, clean));
  const sine = Math.sin(x * 0.12 - SINE_SPEED * tSeconds);
  return mid + noiseAmp * (1 - c) * smoothNoise(x, tSeconds) + sineAmp * c * sine;
}

export function waveformPathAt(tSeconds: number, clean: number, width = 300, mid = 28): string {
  let d = "";
  for (let x = 0; x <= width; x += 2) {
    const y = waveformY(x, tSeconds, clean, mid);
    d += (x ? "L" : "M") + x + " " + Math.round(y * 100) / 100;
  }
  return d;
}

/** Ease `current` toward `target` by ~6% per 60fps frame, frame-rate independent. */
export function approach(current: number, target: number, dtMs: number, perFrame = 0.06): number {
  const factor = 1 - Math.pow(1 - perFrame, dtMs / (1000 / 60));
  return current + (target - current) * factor;
}

/** Cleanliness target for N of 3 completed preparation steps. */
export function cleanTarget(doneSteps: number): number {
  return [0, 0.4, 0.75, 1][Math.max(0, Math.min(3, doneSteps))];
}
