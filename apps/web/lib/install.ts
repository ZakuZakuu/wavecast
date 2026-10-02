// When to suggest installing WaveCast to the home screen (HANDOFF §6.9).
const VISITS_KEY = "wavecast-visits-v1";
const SESSION_KEY = "wavecast-visit-counted";
const FINISHED_KEY = "wavecast-finished-programme-v1";
const SNOOZE_KEY = "wavecast-install-snooze-until-v1";
const ACK_KEY = "wavecast-install-ack-v1";

export const SNOOZE_DAYS = 14;

export type InstallContext = {
  platform: "ios-safari" | "installable" | "other";
  standalone: boolean;
  /** Mouse-driven wide screen: the desktop side card offers a QR code instead. */
  desktop?: boolean;
  visits: number;
  finishedProgramme: boolean;
  snoozedUntil: number;
  acknowledged: boolean;
  now: number;
};

export function shouldOfferInstall(context: InstallContext): boolean {
  if (context.platform === "other" || context.standalone || context.acknowledged || context.desktop) return false;
  if (context.now < context.snoozedUntil) return false;
  return context.finishedProgramme || context.visits >= 2;
}

export function detectPlatform(userAgent: string, maxTouchPoints: number, hasInstallPrompt: boolean): InstallContext["platform"] {
  const iOS = /iPad|iPhone|iPod/.test(userAgent) || (/Macintosh/.test(userAgent) && maxTouchPoints > 1);
  const safari = /Safari/.test(userAgent) && !/CriOS|FxiOS|EdgiOS|OPiOS|GSA\//.test(userAgent);
  if (iOS && safari) return "ios-safari";
  if (hasInstallPrompt) return "installable";
  return "other";
}

function readNumber(key: string): number {
  try {
    const value = Number(window.localStorage.getItem(key));
    return Number.isFinite(value) ? value : 0;
  } catch {
    return 0;
  }
}

/** Counts one visit per browser session. */
export function countVisit(): number {
  try {
    if (window.sessionStorage.getItem(SESSION_KEY)) return readNumber(VISITS_KEY);
    window.sessionStorage.setItem(SESSION_KEY, "1");
    const next = readNumber(VISITS_KEY) + 1;
    window.localStorage.setItem(VISITS_KEY, String(next));
    return next;
  } catch {
    return 0;
  }
}

export function markProgrammeFinished(): void {
  try {
    window.localStorage.setItem(FINISHED_KEY, "1");
  } catch {
    // Best effort only.
  }
}

export function readInstallState(now = Date.now()) {
  let finished = false;
  let acknowledged = false;
  try {
    finished = window.localStorage.getItem(FINISHED_KEY) === "1";
    acknowledged = window.localStorage.getItem(ACK_KEY) === "1";
  } catch {
    // Ignore.
  }
  return { finishedProgramme: finished, acknowledged, snoozedUntil: readNumber(SNOOZE_KEY), now };
}

export function snoozeInstall(now = Date.now()): void {
  try {
    window.localStorage.setItem(SNOOZE_KEY, String(now + SNOOZE_DAYS * 24 * 60 * 60 * 1000));
  } catch {
    // Ignore.
  }
}

export function acknowledgeInstall(): void {
  try {
    window.localStorage.setItem(ACK_KEY, "1");
  } catch {
    // Ignore.
  }
}

export function isStandalone(): boolean {
  if (typeof window === "undefined") return false;
  const nav = navigator as Navigator & { standalone?: boolean };
  return nav.standalone === true || window.matchMedia?.("(display-mode: standalone)").matches === true;
}

/** A computer: wide viewport with a hovering, precise pointer (not a phone or tablet). */
export function isDesktopPointer(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(min-width: 768px) and (hover: hover) and (pointer: fine)").matches;
}
