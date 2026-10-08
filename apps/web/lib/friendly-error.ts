import { ApiRequestError } from "./api";

/** Shows backend/provider messages only when they are already listener-facing Chinese. */
export function friendlyError(message: string | null | undefined, fallback: string): string {
  return message && /[一-鿿]/.test(message) ? message : fallback;
}

/**
 * Whether trying the same request again can help. A 422 means the request itself
 * (the artist or topic) has no playable source, so the listener should rephrase
 * instead of retrying; every other failure (outage, timeout) may succeed later.
 */
export function failureCanRetry(reason: unknown): boolean {
  return !(reason instanceof ApiRequestError && reason.status === 422);
}
