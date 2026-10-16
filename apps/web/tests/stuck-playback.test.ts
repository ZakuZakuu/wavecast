import { describe, expect, it } from "vitest";

import {
  RECOVERY_COOLDOWN_SECONDS,
  SEEK_STUCK_SECONDS,
  STALL_SECONDS,
  stuckPlaybackReason,
  type StuckPlaybackInput,
} from "../lib/stuck-playback";

const NOW = 1_000_000;

function input(patch: Partial<StuckPlaybackInput> = {}): StuckPlaybackInput {
  return {
    nowMs: NOW,
    desiredPlaying: true,
    complete: false,
    currentTime: 820,
    frontierSeconds: 1200,
    lastAdvanceMs: NOW,
    pendingSeekTarget: null,
    pendingSinceMs: null,
    lastRecoveryMs: null,
    ...patch,
  };
}

describe("a player that says it is playing while nothing moves", () => {
  it("leaves a player that is advancing alone", () => {
    expect(stuckPlaybackReason(input({ lastAdvanceMs: NOW - 1_000 }))).toBeNull();
  });

  it("recovers when the audio has not advanced for a while although more is published", () => {
    expect(stuckPlaybackReason(input({ lastAdvanceMs: NOW - STALL_SECONDS * 1000 }))).toBe("not-advancing");
  });

  it("recovers at the playhead the listener was stuck at in the field (13:40, audio published ahead)", () => {
    expect(
      stuckPlaybackReason(input({ currentTime: 820, frontierSeconds: 1230, lastAdvanceMs: NOW - 60_000 })),
    ).toBe("not-advancing");
  });

  it("is only waiting, not stuck, when the playhead has reached the end of the published audio", () => {
    expect(
      stuckPlaybackReason(input({ currentTime: 820, frontierSeconds: 824, lastAdvanceMs: NOW - 60_000 })),
    ).toBeNull();
  });

  it("does nothing when the listener has paused", () => {
    expect(stuckPlaybackReason(input({ desiredPlaying: false, lastAdvanceMs: NOW - 60_000 }))).toBeNull();
  });

  it("recovers a seek the element never confirmed", () => {
    expect(
      stuckPlaybackReason(
        input({ pendingSeekTarget: 900, pendingSinceMs: NOW - SEEK_STUCK_SECONDS * 1000, lastAdvanceMs: NOW }),
      ),
    ).toBe("seek-unconfirmed");
  });

  it("gives a fresh seek time to be confirmed", () => {
    expect(stuckPlaybackReason(input({ pendingSeekTarget: 900, pendingSinceMs: NOW - 1_000 }))).toBeNull();
  });

  it("does not call a seek past the published end stuck: the programme has to catch up", () => {
    expect(
      stuckPlaybackReason(input({ pendingSeekTarget: 1300, pendingSinceMs: NOW - 60_000, lastAdvanceMs: NOW - 60_000 })),
    ).toBeNull();
  });

  it("can recover in the first seconds of the page's life (the clock starts near zero)", () => {
    expect(
      stuckPlaybackReason(input({ nowMs: 9_000, lastAdvanceMs: 1_000, lastRecoveryMs: null })),
    ).toBe("not-advancing");
  });

  it("does not recover again straight after a recovery", () => {
    expect(
      stuckPlaybackReason(
        input({ lastAdvanceMs: NOW - 60_000, lastRecoveryMs: NOW - (RECOVERY_COOLDOWN_SECONDS - 1) * 1000 }),
      ),
    ).toBeNull();
    expect(
      stuckPlaybackReason(
        input({ lastAdvanceMs: NOW - 60_000, lastRecoveryMs: NOW - RECOVERY_COOLDOWN_SECONDS * 1000 }),
      ),
    ).toBe("not-advancing");
  });

  it("recovers a finished programme that stopped part-way, but not one that played to the end", () => {
    const base = { complete: true, frontierSeconds: 1500, lastAdvanceMs: NOW - 60_000 };
    expect(stuckPlaybackReason(input({ ...base, currentTime: 700 }))).toBe("not-advancing");
    expect(stuckPlaybackReason(input({ ...base, currentTime: 1500 }))).toBeNull();
  });
});
