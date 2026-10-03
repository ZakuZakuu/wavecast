import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  claimVisitPrompt,
  finishedProgrammeCount,
  LOGIN_NUDGE_SNOOZE_DAYS,
  loginNudgeSnoozedUntil,
  PROGRAMME_FINISHED_EVENT,
  recordFinishedProgramme,
  shouldShowLoginNudge,
  snoozeLoginNudge,
  visitPrompt,
} from "../lib/login-nudge";

const base = { signedIn: false, finishedCount: 2, snoozedUntil: 0, visitPrompt: null, now: 1_000_000 } as const;

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
});

describe("login nudge rules", () => {
  it("appears for a guest from the second finished programme", () => {
    expect(shouldShowLoginNudge({ ...base, finishedCount: 1 })).toBe(false);
    expect(shouldShowLoginNudge(base)).toBe(true);
  });

  it("never appears once signed in", () => {
    expect(shouldShowLoginNudge({ ...base, signedIn: true })).toBe(false);
  });

  it("stays away for 7 days after 以后再说", () => {
    snoozeLoginNudge(base.now);
    const until = loginNudgeSnoozedUntil();
    expect(until).toBe(base.now + LOGIN_NUDGE_SNOOZE_DAYS * 86_400_000);
    expect(shouldShowLoginNudge({ ...base, snoozedUntil: until, now: until - 1 })).toBe(false);
    expect(shouldShowLoginNudge({ ...base, snoozedUntil: until, now: until })).toBe(true);
  });

  it("does not appear in a visit where the install guide already did", () => {
    expect(shouldShowLoginNudge({ ...base, visitPrompt: "install" })).toBe(false);
    expect(shouldShowLoginNudge({ ...base, visitPrompt: "login" })).toBe(true);
  });
});

describe("one prompt per visit", () => {
  it("lets only the first kind claim the visit", () => {
    expect(visitPrompt()).toBeNull();
    expect(claimVisitPrompt("install")).toBe(true);
    expect(claimVisitPrompt("install")).toBe(true);
    expect(claimVisitPrompt("login")).toBe(false);
    expect(visitPrompt()).toBe("install");
  });
});

describe("finished programmes", () => {
  it("counts distinct programmes and announces each finish", () => {
    const listener = vi.fn();
    window.addEventListener(PROGRAMME_FINISHED_EVENT, listener);
    expect(recordFinishedProgramme("e1")).toBe(1);
    expect(recordFinishedProgramme("e1")).toBe(1);
    expect(recordFinishedProgramme("e2")).toBe(2);
    expect(finishedProgrammeCount()).toBe(2);
    expect(listener).toHaveBeenCalledTimes(3);
    window.removeEventListener(PROGRAMME_FINISHED_EVENT, listener);
  });
});
