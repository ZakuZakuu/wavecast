import { beforeEach, describe, expect, it } from "vitest";

import {
  clearNowPlayingSession,
  isSessionFresh,
  primePausedProgress,
  readNowPlayingSession,
  restorePosition,
  SESSION_KEY,
  SESSION_MAX_AGE_MS,
  writeNowPlayingSession,
} from "../lib/now-playing-session";

const now = 1_800_000_000_000;

describe("now playing session", () => {
  beforeEach(() => window.localStorage.clear());

  it("round-trips the target, position and playing flag", () => {
    writeNowPlayingSession({ target: { seedId: "s1", episodeId: "e1" }, positionSeconds: 312.5, playing: true }, now);
    expect(readNowPlayingSession(now + 1000)).toEqual({
      target: { seedId: "s1", episodeId: "e1" }, positionSeconds: 312.5, playing: true, updatedAt: now,
    });
    clearNowPlayingSession();
    expect(readNowPlayingSession(now)).toBeNull();
  });

  it("expires after 12 hours and removes the stale record", () => {
    writeNowPlayingSession({ target: { episodeId: "e1" }, positionSeconds: 10, playing: false }, now);
    expect(readNowPlayingSession(now + SESSION_MAX_AGE_MS)).not.toBeNull();
    expect(readNowPlayingSession(now + SESSION_MAX_AGE_MS + 1)).toBeNull();
    expect(window.localStorage.getItem(SESSION_KEY)).toBeNull();
  });

  it("rejects malformed or future-dated records", () => {
    window.localStorage.setItem(SESSION_KEY, "{not json");
    expect(readNowPlayingSession(now)).toBeNull();
    window.localStorage.setItem(SESSION_KEY, JSON.stringify({ target: {}, positionSeconds: 1, playing: false, updatedAt: now }));
    expect(readNowPlayingSession(now)).toBeNull();
    expect(isSessionFresh({ target: { episodeId: "e" }, positionSeconds: 0, playing: false, updatedAt: now + 3_600_000 }, now)).toBe(false);
  });

  it("prefers the server checkpoint only when it is newer and different", () => {
    const session = { target: { episodeId: "e1" }, positionSeconds: 300, playing: true, updatedAt: now };
    expect(restorePosition(session, null)).toBe(300);
    expect(restorePosition(session, { positionSeconds: 900, lastActivityAt: now + 60_000 })).toBe(900);
    expect(restorePosition(session, { positionSeconds: 900, lastActivityAt: now - 60_000 })).toBe(300);
    expect(restorePosition(session, { positionSeconds: 302, lastActivityAt: now + 60_000 })).toBe(300);
    expect(restorePosition(session, { positionSeconds: 900, lastActivityAt: null })).toBe(300);
  });

  it("primes the hook checkpoint as paused", () => {
    primePausedProgress("e1", 42, now);
    expect(JSON.parse(window.localStorage.getItem("wavecast-program-progress:e1")!)).toEqual({
      positionSeconds: 42, updatedAtMs: now, continueWhileHidden: false,
    });
  });
});
