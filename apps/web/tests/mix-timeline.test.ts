import { describe, expect, it } from "vitest";

import { activeMixClipsAt, buildMixPlan, clampMixPosition, evaluateGain, linearPositionToMixPosition, mixPositionToLinearPosition, scheduleAt } from "../lib/mix-timeline";
import type { LiveEpisode } from "../lib/types";

const episode: LiveEpisode = {
  id: "phase6-fixture", seed_id: "seed", listener_id: "listener", version: 1,
  state: "MATERIALIZED", generation_mode: "FULL", current_segment_id: "music-a",
  playback_position_seconds: 0, is_listener_active: true, is_playing: true,
  program_estimated_duration_seconds: 90, generated_frontier_seconds: 90,
  buffer_ahead_seconds: 90, committed_frontier_seconds: 90, timeline_duration_seconds: 90,
  segments: [
    { id: "music-a", chapter_id: "a", order: 0, kind: "MUSIC", state: "AUDIO_READY", planned_duration_seconds: 40, actual_duration_seconds: 40, audio_source_url: "/a.mp3", duration_seconds: 40, track_ref: "a", title: "A", artist: "Artist", narration_text: null, asset_ref: null },
    { id: "voice-a", chapter_id: "a", order: 1, kind: "NARRATION", state: "AUDIO_READY", planned_duration_seconds: 8, actual_duration_seconds: 8, audio_source_url: "/voice-a.mp3", duration_seconds: 8, track_ref: null, title: "Voice", artist: null, narration_text: "Bridge", asset_ref: null },
    { id: "music-b", chapter_id: "b", order: 2, kind: "MUSIC", state: "AUDIO_READY", planned_duration_seconds: 35, actual_duration_seconds: 35, audio_source_url: "/b.mp3", duration_seconds: 35, track_ref: "b", title: "B", artist: "Artist", narration_text: null, asset_ref: null },
  ],
};

describe("deterministic mix timeline", () => {
  it("creates music and voice overlap with an incoming crossfade", () => {
    const plan = buildMixPlan(episode);
    const musicA = plan.clips.find((clip) => clip.segmentId === "music-a")!;
    const voice = plan.clips.find((clip) => clip.segmentId === "voice-a")!;
    const musicB = plan.clips.find((clip) => clip.segmentId === "music-b")!;

    expect(musicA.timelineStartSeconds).toBeLessThan(voice.timelineStartSeconds);
    expect(musicB.timelineStartSeconds).toBeLessThan(voice.timelineStartSeconds + 8);
    expect(musicA.timelineStartSeconds + musicA.playableDurationSeconds).toBeGreaterThan(musicB.timelineStartSeconds);
    expect(evaluateGain(musicA, voice.timelineStartSeconds + 0.5)).toBeLessThan(1);
    expect(activeMixClipsAt(plan, voice.timelineStartSeconds + 0.5).map((clip) => clip.lane)).toEqual(["MUSIC", "VOICE", "MUSIC"] );
  });

  it("holds ducking through narration and restores after release", () => {
    const plan = buildMixPlan(episode);
    const musicA = plan.clips.find((clip) => clip.segmentId === "music-a")!;
    const musicB = plan.clips.find((clip) => clip.segmentId === "music-b")!;

    expect(evaluateGain(musicA, 10)).toBe(1);
    expect(evaluateGain(musicB, 41)).toBeCloseTo(0.35);
    expect(evaluateGain(musicB, 47.5)).toBe(1);
  });

  it("round-trips overlap positions through the linear runtime seam", () => {
    const plan = buildMixPlan(episode);
    const mixPosition = 39.5;
    const linear = mixPositionToLinearPosition(episode, plan, mixPosition);
    const roundTrip = linearPositionToMixPosition(episode, plan, linear.linearPositionSeconds);

    expect(linear.segmentId).toBe("voice-a");
    expect(linear.linearPositionSeconds).toBe(40.5);
    expect(roundTrip.mixPositionSeconds).toBe(mixPosition);
    expect(roundTrip.segmentId).toBe("voice-a");
  });

  it("is deterministic and produces bounded seek schedules", () => {
    const first = buildMixPlan(episode);
    const second = buildMixPlan(episode);
    expect(first).toEqual(second);
    expect(clampMixPosition(first, -2)).toBe(0);
    expect(clampMixPosition(first, 999)).toBe(first.durationSeconds);
    expect(scheduleAt(first, 40).every(({ sourceTimeSeconds }) => sourceTimeSeconds >= 0)).toBe(true);
  });
});
