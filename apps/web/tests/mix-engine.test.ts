import { afterEach, describe, expect, it, vi } from "vitest";

import { MixEngine } from "../lib/mix-engine";
import { buildMixPlan } from "../lib/mix-timeline";
import type { LiveEpisode } from "../lib/types";

const episode: LiveEpisode = {
  id: "engine-fixture", seed_id: "seed", listener_id: "listener", version: 1,
  state: "MATERIALIZED", generation_mode: "FULL", current_segment_id: "music-a",
  playback_position_seconds: 0, is_listener_active: true, is_playing: true,
  program_estimated_duration_seconds: 20, generated_frontier_seconds: 20,
  buffer_ahead_seconds: 20, committed_frontier_seconds: 20, timeline_duration_seconds: 20,
  segments: [{
    id: "music-a", chapter_id: "a", order: 0, kind: "MUSIC", state: "AUDIO_READY",
    planned_duration_seconds: 20, actual_duration_seconds: 20, audio_source_url: "/a.mp3",
    duration_seconds: 20, track_ref: "a", title: "A", artist: "Artist", narration_text: null, asset_ref: null,
  }],
};

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
    engine.setPlan(buildMixPlan(episode));
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
