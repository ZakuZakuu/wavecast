import { describe, expect, it } from "vitest";

import { createEffectGenerationGuard, createIndependentSynchronizationTasks, createSynchronizationGuard } from "../lib/episode-synchronization";

describe("episode start effect lifecycle", () => {
  it("invalidates a deferred leave when Strict Mode immediately mounts the effect again", () => {
    const guard = createEffectGenerationGuard();
    const firstMount = guard.start();
    const strictModeRemount = guard.start();

    expect(guard.isCurrent(firstMount)).toBe(false);
    expect(guard.isCurrent(strictModeRemount)).toBe(true);
  });

  it("keeps the current generation eligible to leave on a real unmount", () => {
    const guard = createEffectGenerationGuard();
    const activeMount = guard.start();

    expect(guard.isCurrent(activeMount)).toBe(true);
  });
});

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


describe("independent episode synchronization tasks", () => {
  it("continues heartbeats while buffer generation is still in flight", async () => {
    let releaseBuffer!: () => void;
    const bufferBlocked = new Promise<void>((resolve) => {
      releaseBuffer = resolve;
    });
    let heartbeatCalls = 0;
    let bufferCalls = 0;

    const tasks = createIndependentSynchronizationTasks(
      async () => {
        heartbeatCalls += 1;
      },
      async () => {
        bufferCalls += 1;
        await bufferBlocked;
      },
    );

    const firstBuffer = tasks.buffer();
    await tasks.heartbeat();
    await tasks.heartbeat();

    expect(bufferCalls).toBe(1);
    expect(heartbeatCalls).toBe(2);

    releaseBuffer();
    await firstBuffer;
  });

  it("coalesces overlapping buffer generation requests without blocking heartbeat", async () => {
    let releaseBuffer!: () => void;
    const bufferBlocked = new Promise<void>((resolve) => {
      releaseBuffer = resolve;
    });
    let heartbeatCalls = 0;
    let bufferCalls = 0;

    const tasks = createIndependentSynchronizationTasks(
      async () => {
        heartbeatCalls += 1;
      },
      async () => {
        bufferCalls += 1;
        await bufferBlocked;
      },
    );

    const firstBuffer = tasks.buffer();
    const overlappingBuffer = tasks.buffer();
    await tasks.heartbeat();

    expect(bufferCalls).toBe(1);
    expect(heartbeatCalls).toBe(1);

    releaseBuffer();
    await Promise.all([firstBuffer, overlappingBuffer]);
  });
});
