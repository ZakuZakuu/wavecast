// Guest sign-in hints (HANDOFF follow-up): the one-off card after a guest
// finishes their second programme, kept apart from the install guide.
const FINISHED_IDS_KEY = "wavecast-finished-programmes-v1";
const SNOOZE_KEY = "wavecast-login-nudge-snooze-until-v1";
/** sessionStorage: which one-off prompt this visit has used ("install" | "login"). */
const VISIT_PROMPT_KEY = "wavecast-visit-prompt-v1";

export const LOGIN_NUDGE_SNOOZE_DAYS = 7;
/** The card appears when this many distinct programmes have been finished. */
export const LOGIN_NUDGE_AFTER_FINISHED = 2;
export const PROGRAMME_FINISHED_EVENT = "wavecast-programme-finished";

export type VisitPrompt = "install" | "login";

function readIds(): string[] {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(FINISHED_IDS_KEY) ?? "[]");
    return Array.isArray(parsed) ? parsed.filter((value): value is string => typeof value === "string") : [];
  } catch {
    return [];
  }
}

/** Distinct programmes this browser has listened to the end. */
export function finishedProgrammeCount(): number {
  if (typeof window === "undefined") return 0;
  return readIds().length;
}

/** Records a finished programme (once per id) and announces it. Returns the count. */
export function recordFinishedProgramme(programmeId: string): number {
  if (typeof window === "undefined") return 0;
  const ids = readIds();
  if (!ids.includes(programmeId)) {
    ids.push(programmeId);
    try {
      window.localStorage.setItem(FINISHED_IDS_KEY, JSON.stringify(ids.slice(-50)));
    } catch {
      // Best effort only.
    }
  }
  window.dispatchEvent(new CustomEvent(PROGRAMME_FINISHED_EVENT, { detail: { count: ids.length } }));
  return ids.length;
}

export function visitPrompt(): VisitPrompt | null {
  try {
    const value = window.sessionStorage.getItem(VISIT_PROMPT_KEY);
    return value === "install" || value === "login" ? value : null;
  } catch {
    return null;
  }
}

/** At most one one-off prompt per visit: claims the slot; false if another prompt has it. */
export function claimVisitPrompt(kind: VisitPrompt): boolean {
  const current = visitPrompt();
  if (current && current !== kind) return false;
  try {
    window.sessionStorage.setItem(VISIT_PROMPT_KEY, kind);
  } catch {
    // Without sessionStorage the slot cannot be held; still show once.
  }
  return true;
}

export function loginNudgeSnoozedUntil(): number {
  try {
    const value = Number(window.localStorage.getItem(SNOOZE_KEY));
    return Number.isFinite(value) ? value : 0;
  } catch {
    return 0;
  }
}

export function snoozeLoginNudge(now = Date.now()): void {
  try {
    window.localStorage.setItem(SNOOZE_KEY, String(now + LOGIN_NUDGE_SNOOZE_DAYS * 24 * 60 * 60 * 1000));
  } catch {
    // Ignore.
  }
}

export type LoginNudgeContext = {
  signedIn: boolean;
  finishedCount: number;
  snoozedUntil: number;
  visitPrompt: VisitPrompt | null;
  now: number;
};

/** Never for signed-in users; from the second finished programme; 7-day snooze; one prompt per visit. */
export function shouldShowLoginNudge(context: LoginNudgeContext): boolean {
  if (context.signedIn) return false;
  if (context.finishedCount < LOGIN_NUDGE_AFTER_FINISHED) return false;
  if (context.now < context.snoozedUntil) return false;
  return context.visitPrompt !== "install";
}
