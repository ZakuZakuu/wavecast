import { describe, expect, it } from "vitest";

import { canUseArmedHandoff, isPlaybackReadySegment, isProgramPlaybackComplete, isSeekAllowed, nextVisibleSegment, reconcileBrowserPosition, remainingSegmentSeconds, segmentAtPosition, segmentOffset, shouldArmHandoff } from "../lib/playback";
import type { LiveEpisode } from "../lib/types";

const episode: LiveEpisode = {
  id: "episode", seed_id: "seed", listener_id: "listener", version: 1, state: "STREAMING", generation_mode: "PROGRESSIVE", current_segment_id: "opening",
  playback_position_seconds: 0, is_listener_active: true, is_playing: true,
  program_estimated_duration_seconds: 30 * 60, generated_frontier_seconds: 22, buffer_ahead_seconds: 22,
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

  it("keeps audio offset tied to committed position across segment changes", () => {
    const committed = { ...episode, current_segment_id: "bridge", playback_position_seconds: 42 };
    const previewPosition = 54;

    expect(segmentOffset(committed, "bridge", committed.playback_position_seconds)).toBe(10);
    expect(segmentOffset(committed, "bridge", committed.playback_position_seconds)).not.toBe(
      segmentOffset(committed, "bridge", previewPosition),
    );
  });

  it("keeps the old audio offset until a cross-segment seek response arrives", () => {
    const previous = { ...episode, current_segment_id: "opening", playback_position_seconds: 12 };
    const target = { ...episode, current_segment_id: "bridge", playback_position_seconds: 42 };

    expect(reconcileBrowserPosition(12, previous, previous)).toBe(12);
    expect(reconcileBrowserPosition(12, previous, target, 42)).toBe(42);
  });

  it("does not consume a seek target from an unrelated snapshot", () => {
    const previous = { ...episode, current_segment_id: "opening", playback_position_seconds: 12 };
    const checkpoint = { ...previous, playback_position_seconds: 13 };
    const seekResponse = { ...previous, current_segment_id: "bridge", playback_position_seconds: 42 };

    expect(reconcileBrowserPosition(12, previous, checkpoint)).toBe(12);
    expect(reconcileBrowserPosition(12, checkpoint, seekResponse, 42)).toBe(42);
  });

  it("lets the successful seek response coexist with an equivalent SSE snapshot", () => {
    const previous = { ...episode, current_segment_id: "opening", playback_position_seconds: 32 };
    const sseSnapshot = { ...previous, playback_position_seconds: 10 };
    const seekResponse = { ...sseSnapshot };

    expect(reconcileBrowserPosition(32, previous, sseSnapshot)).toBe(32);
    expect(reconcileBrowserPosition(10, sseSnapshot, seekResponse)).toBe(10);
  });

  it("keeps the browser clock ahead when an unrelated newer snapshot has the same playback anchor", () => {
    const serverSnapshot = { ...episode, version: 2, playback_position_seconds: 5 };
    const unrelatedNewerSnapshot = { ...serverSnapshot, version: 3, generated_frontier_seconds: 48 };

    expect(reconcileBrowserPosition(11, serverSnapshot, unrelatedNewerSnapshot)).toBe(11);
  });

  it("does not let a late checkpoint move the browser clock backwards", () => {
    const previousSnapshot = { ...episode, playback_position_seconds: 25 };
    const checkpoint = { ...previousSnapshot, playback_position_seconds: 30 };

    expect(reconcileBrowserPosition(32, previousSnapshot, checkpoint)).toBe(32);
  });

  it("applies an explicit backward seek even when the segment is unchanged", () => {
    const serverSnapshot = { ...episode, playback_position_seconds: 32 };
    const afterSeek = { ...serverSnapshot, playback_position_seconds: 10 };

    expect(reconcileBrowserPosition(32, serverSnapshot, afterSeek, 10)).toBe(10);
  });

  it("adopts the new server anchor when the current segment changes", () => {
    const previous = { ...episode, current_segment_id: "opening", playback_position_seconds: 21 };
    const next = { ...episode, current_segment_id: "bridge", playback_position_seconds: 32 };

    expect(reconcileBrowserPosition(21, previous, next)).toBe(32);
  });

  it("restores the persisted position on initial load", () => {
    const restored = { ...episode, playback_position_seconds: 12 };

    expect(reconcileBrowserPosition(0, null, restored)).toBe(12);
  });

  it("records completion only after the whole program frontier is consumed", () => {
    const completed = {
      ...episode,
      state: "MATERIALIZED",
      is_playing: false,
      generated_frontier_seconds: 58,
      program_estimated_duration_seconds: 58,
      segments: episode.segments.map((segment) => ({
        ...segment,
        state: segment.state === "SKIPPED" ? "SKIPPED" as const : "PLAYED" as const,
      })),
    };
    expect(isProgramPlaybackComplete(completed)).toBe(true);
    expect(isProgramPlaybackComplete({ ...completed, state: "STREAMING", generated_frontier_seconds: 22 })).toBe(false);
    expect(isProgramPlaybackComplete({ ...completed, segments: [{ ...completed.segments[0], state: "COMMITTED" }] })).toBe(false);
  });
});


describe("armed browser handoff", () => {
  const current = episode.segments[0];
  const readySuccessor = {
    ...episode.segments[2],
    state: "AUDIO_READY" as const,
  };

  it("arms only an immediate playback-ready future near the media boundary", () => {
    expect(shouldArmHandoff({
      current,
      upcoming: readySuccessor,
      serverCurrentId: current.id,
      transportSegmentId: null,
      remainingSeconds: 1.5,
      armThresholdSeconds: 2,
    })).toBe(true);

    expect(shouldArmHandoff({
      current,
      upcoming: readySuccessor,
      serverCurrentId: current.id,
      transportSegmentId: null,
      remainingSeconds: 5,
      armThresholdSeconds: 2,
    })).toBe(false);

    expect(shouldArmHandoff({
      current,
      upcoming: episode.segments[2],
      serverCurrentId: current.id,
      transportSegmentId: null,
      remainingSeconds: 1,
      armThresholdSeconds: 2,
    })).toBe(false);
  });

  it("invalidates an armed handoff after manual server transport moves", () => {
    expect(canUseArmedHandoff({
      current,
      armedSegment: readySuccessor,
      serverCurrentId: current.id,
      armedFromSegmentId: current.id,
    })).toBe(true);

    expect(canUseArmedHandoff({
      current: readySuccessor,
      armedSegment: readySuccessor,
      serverCurrentId: readySuccessor.id,
      armedFromSegmentId: current.id,
    })).toBe(false);
  });

  it("treats source availability and durable readiness as one preload boundary", () => {
    expect(isPlaybackReadySegment(readySuccessor)).toBe(true);
    expect(isPlaybackReadySegment(episode.segments[2])).toBe(false);
    expect(isPlaybackReadySegment({
      ...readySuccessor,
      audio_source_url: null,
    })).toBe(false);
  });
});


describe("local seek target resolution", () => {
  it("maps a generated timeline position to the same half-open segment boundary as the backend", () => {
    expect(segmentAtPosition(episode, 0)?.id).toBe("opening");
    expect(segmentAtPosition(episode, 21.9)?.id).toBe("opening");
    expect(segmentAtPosition(episode, 22)?.id).toBe("narration");
  });

  it("removes skipped narration from the local seek timeline", () => {
    const skipped = {
      ...episode,
      segments: episode.segments.map((segment) =>
        segment.id === "narration"
          ? { ...segment, state: "SKIPPED" as const }
          : segment.id === "bridge"
            ? { ...segment, state: "AUDIO_READY" as const }
            : segment,
      ),
    };

    expect(segmentAtPosition(skipped, 22)?.id).toBe("bridge");
  });
});
