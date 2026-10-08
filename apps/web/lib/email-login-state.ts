/**
 * Where the email-code sign-in left off, so a reload (or iOS discarding the
 * PWA while the listener fetches the code from their mail app) lands back on
 * the code step instead of asking for the address again. Holds only the
 * address, the step and timestamps: never the code, a token or a session.
 */
export type EmailLoginStep = "email" | "code";

export interface PendingEmailLogin {
  email: string;
  step: EmailLoginStep;
  /** When "send again" opens up (ms since epoch). */
  resendAt: number;
  /** When this record stops being worth restoring (ms since epoch). */
  expiresAt: number;
}

const KEY = "wavecast-email-login-v1";
/** Matches the code's 5 minute validity in the mail. */
export const CODE_VALID_MS = 5 * 60_000;
export const RESEND_COOLDOWN_MS = 60_000;

function finite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function readPendingEmailLogin(now = Date.now()): PendingEmailLogin | null {
  try {
    const raw = window.sessionStorage.getItem(KEY);
    if (!raw) return null;
    const value = JSON.parse(raw) as Partial<PendingEmailLogin> | null;
    if (
      !value
      || typeof value.email !== "string"
      || !value.email.includes("@")
      || value.email.length > 254
      || (value.step !== "email" && value.step !== "code")
      || !finite(value.resendAt)
      || !finite(value.expiresAt)
      // A record can never legitimately outlive the code it waits for.
      || value.expiresAt - now > CODE_VALID_MS
    ) {
      clearPendingEmailLogin();
      return null;
    }
    if (value.expiresAt <= now) {
      clearPendingEmailLogin();
      return null;
    }
    return { email: value.email, step: value.step, resendAt: value.resendAt, expiresAt: value.expiresAt };
  } catch {
    return null;
  }
}

export function writePendingEmailLogin(state: PendingEmailLogin): void {
  try {
    const { email, step, resendAt, expiresAt } = state;
    window.sessionStorage.setItem(KEY, JSON.stringify({ email, step, resendAt, expiresAt }));
  } catch {
    // Private mode or storage off: sign-in still works for this page load.
  }
}

export function clearPendingEmailLogin(): void {
  try {
    window.sessionStorage.removeItem(KEY);
  } catch {
    // Nothing stored, nothing to clear.
  }
}
