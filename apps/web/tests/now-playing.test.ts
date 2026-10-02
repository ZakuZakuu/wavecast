import { describe, expect, it } from "vitest";

import { clampSeek, currentMusicSegment, estimatedTotalSeconds, formatClock, progressLayers, routeChapters, trackLabel } from "../lib/now-playing";
import type { MixPlan } from "../lib/mix-timeline";
import type { LiveEpisode } from "../lib/types";

const music = (id: string, chapter: string, order: number, state: string, title = "Song " + id) => ({
  id, chapter_id: chapter, order, kind: "MUSIC" as const, state: state as never, planned_duration_seconds: 100,
  actual_duration_seconds: 100, audio_source_url: state === "PLANNED" ? null : "/a/" + id, duration_seconds: 100,
  track_ref: id, title, artist: "Artist", narration_text: null, asset_ref: null,
});

const episode: LiveEpisode = {
  id: "e", seed_id: "s", listener_id: "l", version: 1, state: "STREAMING", generation_mode: "PROGRESSIVE",
  current_segment_id: "m1", playback_position_seconds: 0, is_listener_active: true, is_playing: true,
  program_estimated_duration_seconds: 1800, generated_frontier_seconds: 200, buffer_ahead_seconds: 0,
  committed_frontier_seconds: 0, timeline_duration_seconds: 300,
  segments: [
    music("m1", "c1", 0, "PLAYED"),
    { id: "n1", chapter_id: "c2", order: 1, kind: "NARRATION", state: "AUDIO_READY", planned_duration_seconds: 10, actual_duration_seconds: 10, audio_source_url: "/n", duration_seconds: 10, track_ref: null, title: "Track Intro", artist: null, narration_text: "下一首也是这么开头的。", asset_ref: null },
    music("m2", "c2", 2, "AUDIO_READY"),
    music("m3", "c3", 3, "PLANNED", ""),
  ],
};

const plan: MixPlan = {
  schemaVersion: 1, episodeId: "e", durationSeconds: 300,
  clips: [
    { id: "k1", segmentId: "m1", sourceUrl: "", lane: "MUSIC", timelineStartSeconds: 0, sourceOffsetSeconds: 0, playableDurationSeconds: 100, gain: 1, fadeInSeconds: 0, fadeOutSeconds: 0, gainAutomation: [] },
    { id: "k2", segmentId: "n1", sourceUrl: "", lane: "VOICE", timelineStartSeconds: 95, sourceOffsetSeconds: 0, playableDurationSeconds: 10, gain: 1, fadeInSeconds: 0, fadeOutSeconds: 0, gainAutomation: [] },
    { id: "k3", segmentId: "m2", sourceUrl: "", lane: "MUSIC", timelineStartSeconds: 100, sourceOffsetSeconds: 0, playableDurationSeconds: 100, gain: 1, fadeInSeconds: 0, fadeOutSeconds: 0, gainAutomation: [] },
  ],
  segmentStarts: { m1: 0, n1: 95, m2: 100, m3: 200 },
};

describe("progress", () => {
  it("formats clocks", () => {
    expect(formatClock(760)).toBe("12:40");
    expect(formatClock(3725)).toBe("1:02:05");
  });

  it("uses the backend estimate but never less than the prepared frontier", () => {
    expect(estimatedTotalSeconds(episode, { renderedFrontierSeconds: 200, complete: false })).toBe(1800);
    expect(estimatedTotalSeconds({ program_estimated_duration_seconds: 100 }, { renderedFrontierSeconds: 200, complete: false })).toBe(200);
    expect(estimatedTotalSeconds(episode, { renderedFrontierSeconds: 640, complete: true })).toBe(640);
    expect(estimatedTotalSeconds({ program_estimated_duration_seconds: 0 }, null, "DEEP")).toBe(3600);
  });

  it("layers played inside prepared", () => {
    expect(progressLayers(900, 1080, 1800)).toEqual({ playedPct: 50, preparedPct: 60 });
    expect(progressLayers(2000, 1080, 1800).playedPct).toBe(60);
  });

  it("never seeks past the prepared frontier", () => {
    expect(clampSeek(500, 200)).toEqual({ position: 200, overshoot: true });
    expect(clampSeek(150, 200)).toEqual({ position: 150, overshoot: false });
    expect(clampSeek(-3, 200).position).toBe(0);
  });
});

describe("route", () => {
  it("names chapters by index and marks ready / preparing tracks", () => {
    const chapters = routeChapters(episode, plan, "m2", 200);
    expect(chapters.map((chapter) => chapter.title)).toEqual(["第 1 段", "第 2 段", "第 3 段"]);
    expect(chapters[1].status).toBe("playing");
    expect(chapters[0].status).toBe("ready");
    expect(chapters[2].status).toBe("preparing");
    expect(chapters[2].tracks[0].label).toBe("曲目待定");
    expect(chapters[2].tracks[0].ready).toBe(false);
    expect(chapters[1].startSeconds).toBe(95);
    expect(JSON.stringify(chapters)).not.toContain("Track Intro");
  });

  it("finds the music under narration", () => {
    expect(currentMusicSegment(episode, plan, 97)?.id).toBe("m1");
    expect(currentMusicSegment(episode, plan, 150)?.id).toBe("m2");
    expect(currentMusicSegment(episode, null, 0, episode.segments[1])?.id).toBe("m1");
  });

  it("labels tracks", () => {
    expect(trackLabel({ title: "春风吹", artist: "方大同" })).toBe("方大同《春风吹》");
    expect(trackLabel({ title: "", artist: null })).toBe("曲目待定");
  });
});
