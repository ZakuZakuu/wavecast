import { describe, expect, it } from "vitest";

import { createSynchronizationGuard } from "../lib/episode-synchronization";

describe("episode synchronization guard", () => {
  it("does not publish an inactive-session rejection from an invalidated run", () => {
    const guard = createSynchronizationGuard();
    const generation = guard.start();
    let error: string | null = null;

    guard.invalidate();
    if (guard.isCurrent(generation, true)) {
      error = "listener session is inactive; resume it before generating";
    }

    expect(error).toBeNull();
    expect(guard.isCurrent(generation, false)).toBe(false);
  });

  it("allows a new synchronization run after resume", () => {
    const guard = createSynchronizationGuard();
    const oldGeneration = guard.start();

    guard.invalidate();
    const resumedGeneration = guard.start();

    expect(guard.isCurrent(oldGeneration, true)).toBe(false);
    expect(guard.isCurrent(resumedGeneration, true)).toBe(true);
  });
});
