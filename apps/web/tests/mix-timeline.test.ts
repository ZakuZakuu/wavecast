import { describe, expect, it } from "vitest";

import { activeMixClipsAt, clampMixPosition, evaluateGain, linearPositionToMixPosition, mixPlanSignature, mixPositionToLinearPosition, overlapLeadSeconds, scheduleAt } from "../lib/mix-timeline";
import { canonicalPlan } from "./fixtures/canonical-mix-plan";
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
  it("refreshes only for arrangement-relevant segment state changes", () => {
    const signatureFor = (state: LiveEpisode["segments"][number]["state"]) => mixPlanSignature({
      ...episode,
      segments: episode.segments.map((segment, index) => (
        index === 2 ? { ...segment, state } : segment
      )),
    });

    expect(signatureFor("PLANNED")).not.toBe(signatureFor("AUDIO_READY"));
    expect(signatureFor("AUDIO_READY")).toBe(signatureFor("COMMITTED"));
    expect(signatureFor("COMMITTED")).toBe(signatureFor("PLAYED"));
    expect(signatureFor("PLANNED")).not.toBe(signatureFor("SKIPPED"));
    const heartbeatEpisode = { ...episode, version: 2 };
    expect(mixPlanSignature(heartbeatEpisode)).toBe(mixPlanSignature(episode));
  });

  it("creates music and voice overlap with an incoming crossfade", () => {
    const plan = canonicalPlan;
    const musicA = plan.clips.find((clip) => clip.segmentId === "music-a")!;
    const voice = plan.clips.find((clip) => clip.segmentId === "voice-a")!;
    const musicB = plan.clips.find((clip) => clip.segmentId === "music-b")!;

    expect(musicA.timelineStartSeconds).toBeLessThan(voice.timelineStartSeconds);
    expect(musicB.timelineStartSeconds).toBeLessThan(voice.timelineStartSeconds + 8);
    expect(musicA.timelineStartSeconds + musicA.playableDurationSeconds).toBeGreaterThan(musicB.timelineStartSeconds);
    expect(evaluateGain(musicA, voice.timelineStartSeconds + 0.5)).toBeLessThan(1);
    expect(activeMixClipsAt(plan, voice.timelineStartSeconds + 0.5).map((clip) => clip.lane)).toEqual(["MUSIC", "VOICE", "MUSIC"] );
  });

  it("reports the amount of browser-authoritative overlap to arm ahead", () => {
    const plan = canonicalPlan;
    const musicA = plan.clips.find((clip) => clip.segmentId === "music-a")!;
    const voice = plan.clips.find((clip) => clip.segmentId === "voice-a")!;
    const musicB = plan.clips.find((clip) => clip.segmentId === "music-b")!;

    expect(overlapLeadSeconds(musicA, voice)).toBeGreaterThan(0);
    expect(overlapLeadSeconds(voice, musicB)).toBeGreaterThan(0);
    expect(overlapLeadSeconds(null, musicB)).toBe(0);
  });

  it("holds ducking through narration and restores after release", () => {
    const plan = canonicalPlan;
    const musicA = plan.clips.find((clip) => clip.segmentId === "music-a")!;
    const musicB = plan.clips.find((clip) => clip.segmentId === "music-b")!;

    expect(evaluateGain(musicA, 10)).toBe(1);
    expect(evaluateGain(musicB, 47)).toBeCloseTo(0.35);
    expect(evaluateGain(musicB, 47.5)).toBe(1);
  });

  it("round-trips overlap positions through the linear runtime seam", () => {
    const plan = canonicalPlan;
    const mixPosition = 39.5;
    const linear = mixPositionToLinearPosition(episode, plan, mixPosition);
    const roundTrip = linearPositionToMixPosition(episode, plan, linear.linearPositionSeconds);

    expect(linear.segmentId).toBe("voice-a");
    expect(linear.linearPositionSeconds).toBe(40.5);
    expect(roundTrip.mixPositionSeconds).toBe(mixPosition);
    expect(roundTrip.segmentId).toBe("voice-a");
  });

  it("preserves listener time when authority hands off inside an overlap", () => {
    const plan = canonicalPlan;
    const musicA = plan.clips.find((clip) => clip.segmentId === "music-a")!;
    const handoffMixPosition = (
      musicA.timelineStartSeconds + musicA.playableDurationSeconds
    );
    const linear = mixPositionToLinearPosition(
      episode,
      plan,
      handoffMixPosition,
    );
    const restored = linearPositionToMixPosition(
      episode,
      plan,
      linear.linearPositionSeconds,
    );

    expect(linear.segmentId).toBe("voice-a");
    expect(restored.mixPositionSeconds).toBeCloseTo(handoffMixPosition);
  });

  it("is deterministic and produces bounded seek schedules", () => {
    const first = canonicalPlan;
    const second = canonicalPlan;
    expect(first).toEqual(second);
    expect(clampMixPosition(first, -2)).toBe(0);
    expect(clampMixPosition(first, 999)).toBe(first.durationSeconds);
    expect(scheduleAt(first, 40).every(({ sourceTimeSeconds }) => sourceTimeSeconds >= 0)).toBe(true);
  });
});
