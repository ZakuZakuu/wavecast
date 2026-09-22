import { afterEach, describe, expect, it, vi } from "vitest";

import { MixEngine } from "../lib/mix-engine";
import { canonicalPlan } from "./fixtures/canonical-mix-plan";
function fakeAudioContext(): AudioContext {
  const node = { connect: vi.fn(() => node) };
  return {
    destination: {},
    createGain: vi.fn(() => ({ gain: { value: 1 } })),
    createMediaElementSource: vi.fn(() => node),
    resume: vi.fn(() => Promise.resolve()),
    close: vi.fn(() => Promise.resolve()),
  } as unknown as AudioContext;
}

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("MixEngine transport ownership", () => {
  it("does not reset its clock when React echoes an internal tick", () => {
    vi.useFakeTimers();
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
    let now = 0;
    const positions: number[] = [];
    const engine = new MixEngine({
      onPositionChange: (position) => positions.push(position),
      onEnded: vi.fn(),
      audioContextFactory: fakeAudioContext,
      clock: () => now,
    });
    engine.setPlan(canonicalPlan);
    engine.sync(0, true);
    now = 0.1;
    (engine as unknown as { tick: () => void }).tick();
    now = 0.3;
    engine.sync(0.1, true);
    now = 0.4;
    (engine as unknown as { tick: () => void }).tick();

    expect(positions).toEqual([0.1, 0.4]);
    engine.dispose();
  });
});
