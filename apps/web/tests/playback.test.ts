import { describe, expect, it } from "vitest";

import { isSeekAllowed, nextVisibleSegment, reconcileBrowserPosition, remainingSegmentSeconds } from "../lib/playback";
import type { LiveEpisode } from "../lib/types";

const episode: LiveEpisode = {
  id: "episode", seed_id: "seed", listener_id: "listener", version: 1, state: "STREAMING", generation_mode: "PROGRESSIVE", current_segment_id: "opening",
  playback_position_seconds: 0, is_listener_active: true, is_playing: true,
  program_estimated_duration_seconds: 30 * 60, generated_frontier_seconds: 22,
  committed_frontier_seconds: 0, timeline_duration_seconds: 58,
  segments: [
    { id: "opening", chapter_id: "one", order: 0, kind: "MUSIC", state: "AUDIO_READY", planned_duration_seconds: 22, actual_duration_seconds: 22, audio_source_url: "/api/audio/mock/music/mock%3Aopening?duration=22", duration_seconds: 22, track_ref: "mock:opening", title: "Opening", artist: "Artist", narration_text: null, asset_ref: null },
    { id: "narration", chapter_id: "two", order: 1, kind: "NARRATION", state: "PLANNED", planned_duration_seconds: 10, actual_duration_seconds: null, audio_source_url: null, duration_seconds: 10, track_ref: null, title: "Narration", artist: null, narration_text: null, asset_ref: null },
    { id: "bridge", chapter_id: "two", order: 2, kind: "MUSIC", state: "PLANNED", planned_duration_seconds: 26, actual_duration_seconds: null, audio_source_url: "/api/audio/mock/music/mock%3Abridge?duration=24", duration_seconds: 26, track_ref: "mock:bridge", title: "Bridge", artist: "Artist", narration_text: null, asset_ref: null },
  ],
};

describe("generated-frontier player behavior", () => {
  it("does not allow a listener to seek into ungenerated future", () => {
    expect(isSeekAllowed(episode, 22)).toBe(true);
    expect(isSeekAllowed(episode, 23)).toBe(false);
  });

  it("surfaces a known music segment for next when narration is unfinished", () => {
    expect(nextVisibleSegment(episode)?.id).toBe("bridge");
  });

  it("uses only the segment-local remaining duration after seek or restore", () => {
    const restored = { ...episode, playback_position_seconds: 12 };
    expect(remainingSegmentSeconds(restored, restored.segments[0])).toBe(10);
  });

  it("keeps the browser clock ahead when an unrelated newer snapshot has the same playback anchor", () => {
    const serverSnapshot = { ...episode, version: 2, playback_position_seconds: 5 };
    const unrelatedNewerSnapshot = { ...serverSnapshot, version: 3, generated_frontier_seconds: 48 };

    expect(reconcileBrowserPosition(11, serverSnapshot, unrelatedNewerSnapshot)).toBe(11);
  });
});
