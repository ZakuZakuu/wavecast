// Whether this device has already been shown the 电台指南 on its own (the first visit to 调频).
// Kept on the device: a guest has no account.
const SEEN_KEY = "wavecast-station-guide-seen-v1";

export function stationGuideSeen(): boolean {
  try {
    return window.localStorage.getItem(SEEN_KEY) === "1";
  } catch {
    // Without storage it would open on every visit; treat it as seen instead.
    return true;
  }
}

export function markStationGuideSeen(): void {
  try {
    window.localStorage.setItem(SEEN_KEY, "1");
  } catch {
    // Nothing stored, nothing remembered.
  }
}

/** 重看新手引导: the 电台指南 opens by itself again. */
export function resetStationGuide(): void {
  try {
    window.localStorage.removeItem(SEEN_KEY);
  } catch {
    // Nothing stored, nothing to clear.
  }
}
