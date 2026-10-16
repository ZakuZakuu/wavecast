/**
 * Notices a player that says it is playing while nothing moves.
 *
 * Observed on an iPhone: after the page had been in the background and the listener skipped ahead
 * three times, the screen kept showing "playing", the progress bar stood still and neither a drag
 * nor a skip did anything; leaving the programme and resuming it fixed it.  The audio element can be
 * left with a seek it never confirms (the player keeps that seek pending and then neither reports a
 * position nor starts playback) or simply stops advancing without an event.  Neither raises an
 * error, so something has to look at the clock instead of waiting for an event that will not come.
 */

/** The audio has not moved for this long while the listener wants it playing. */
export const STALL_SECONDS = 6;
/** A requested seek that the element has not confirmed for this long is stuck. */
export const SEEK_STUCK_SECONDS = 5;
/** Never recover more often than this: a reload is itself a stall. */
export const RECOVERY_COOLDOWN_SECONDS = 15;
/** Published audio must reach this far past the playhead, or the player is only waiting for more. */
export const RUNWAY_SECONDS = 8;

export type StuckPlaybackInput = {
  nowMs: number;
  /** What the listener wants: the play button shows "playing". */
  desiredPlaying: boolean;
  /** The programme is fully rendered; there is nothing left to wait for. */
  complete: boolean;
  /** Where the media element is. */
  currentTime: number;
  /** The end of the published audio. */
  frontierSeconds: number;
  /** When `currentTime` last changed. */
  lastAdvanceMs: number;
  /** The seek the player is still waiting to apply, if any. */
  pendingSeekTarget: number | null;
  /** When that seek became pending. */
  pendingSinceMs: number | null;
  /** When the player last tried to recover itself; null if it never has. */
  lastRecoveryMs: number | null;
};

export type StuckReason = "not-advancing" | "seek-unconfirmed";

export function stuckPlaybackReason(input: StuckPlaybackInput): StuckReason | null {
  if (!input.desiredPlaying) return null;
  if (
    input.lastRecoveryMs !== null
    && input.nowMs - input.lastRecoveryMs < RECOVERY_COOLDOWN_SECONDS * 1000
  ) return null;

  const published = Math.max(0, input.frontierSeconds);

  if (input.pendingSeekTarget !== null && input.pendingSinceMs !== null) {
    const waited = (input.nowMs - input.pendingSinceMs) / 1000;
    // A target past the published end is waiting for the programme to catch up, which is not a fault.
    const reachable = input.pendingSeekTarget <= published - 0.5;
    if (waited >= SEEK_STUCK_SECONDS && reachable) return "seek-unconfirmed";
    return null;
  }

  const stalled = (input.nowMs - input.lastAdvanceMs) / 1000;
  // A finished programme only needs something left to play; a growing one needs a real runway,
  // otherwise the player is simply waiting for the next chunk to be published.
  const runway = input.complete ? 1 : RUNWAY_SECONDS;
  if (stalled >= STALL_SECONDS && published - input.currentTime >= runway) return "not-advancing";
  return null;
}
