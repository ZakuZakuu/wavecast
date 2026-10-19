import { createElement } from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { LiveEpisode, ProgramRenderManifest } from "../lib/types";

const episode: LiveEpisode = {
  id: "episode-1", seed_id: "seed-1", listener_id: "listener", version: 1, state: "STREAMING",
  generation_mode: "PROGRESSIVE", current_segment_id: "opening", playback_position_seconds: 0,
  is_listener_active: true, is_playing: true, program_estimated_duration_seconds: 1800,
  generated_frontier_seconds: 120, buffer_ahead_seconds: 120, committed_frontier_seconds: 0,
  timeline_duration_seconds: 120,
  segments: [
    { id: "opening", chapter_id: "one", order: 0, kind: "MUSIC", state: "AUDIO_READY", planned_duration_seconds: 120, actual_duration_seconds: 120, audio_source_url: "/a", duration_seconds: 120, track_ref: "t", title: "Opening", artist: "Artist", narration_text: null, asset_ref: null },
  ],
};

const manifest: ProgramRenderManifest = {
  schemaVersion: 1, episodeId: "episode-1", revision: "r1", chunkDurationSeconds: 6,
  holdbackSeconds: 30, renderedFrontierSeconds: 90, complete: false,
  chunks: [{ index: 0, startSeconds: 0, durationSeconds: 90, planFingerprint: "p", contentSha256: "c", assetKey: "k", audioUrl: "/c" }],
  streamUrl: "/stream.m3u8",
};

const api = vi.hoisted(() => ({
  get: vi.fn(),
  start: vi.fn(),
  programRenderStatus: vi.fn(),
  programRender: vi.fn(),
  mixPlan: vi.fn(),
  heartbeat: vi.fn(),
  programCheckpoint: vi.fn(),
  recordUserEvent: vi.fn(),
  resume: vi.fn(),
}));

vi.mock("../lib/api", () => ({ api, ApiRequestError: class extends Error { status = 0; } }));
vi.mock("../lib/episode-events", () => ({ subscribeToEpisodeEvents: () => () => undefined }));

import { useProgrammePlayback, type ProgrammePlayback } from "../lib/use-programme-playback";

let latest: ProgrammePlayback | null = null;
function Probe({ episodeId }: { episodeId: string }) {
  latest = useProgrammePlayback({ episodeId });
  return null;
}

async function flush() {
  for (let index = 0; index < 5; index += 1) {
    await act(async () => { await Promise.resolve(); });
  }
}

describe("useProgrammePlayback", () => {
  let root: Root;
  let container: HTMLDivElement;

  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    window.localStorage.clear();
    window.sessionStorage.clear();
    api.get.mockResolvedValue(episode);
    api.programRenderStatus.mockResolvedValue(manifest);
    api.programRender.mockResolvedValue(manifest);
    api.mixPlan.mockRejectedValue(new Error("no plan"));
    api.heartbeat.mockResolvedValue(episode);
    api.programCheckpoint.mockResolvedValue(episode);
    api.recordUserEvent.mockResolvedValue(undefined);
    container = document.createElement("div");
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    latest = null;
    vi.clearAllMocks();
  });

  it("loads the episode, reuses the published manifest and never seeks past the rendered frontier", async () => {
    await act(async () => { root.render(createElement(Probe, { episodeId: "episode-1" })); });
    await flush();
    expect(api.get).toHaveBeenCalledWith("episode-1");
    expect(latest?.localEpisode?.id).toBe("episode-1");
    expect(latest?.programManifest?.renderedFrontierSeconds).toBe(90);
    expect(api.heartbeat).toHaveBeenCalledWith("episode-1");

    act(() => latest!.commitSeek(500));
    expect(latest!.browserPosition).toBe(90);
    act(() => latest!.commitSeek(-20));
    expect(latest!.browserPosition).toBe(0);
  });

  describe("next", () => {
    const clip = (id: string, lane: "MUSIC" | "VOICE", start: number, duration: number) => ({
      id, segmentId: id, sourceUrl: "/x", lane, timelineStartSeconds: start, sourceOffsetSeconds: 0,
      playableDurationSeconds: duration, gain: 1, fadeInSeconds: 0, fadeOutSeconds: 0, gainAutomation: [],
    });
    const withHost: LiveEpisode = {
      ...episode,
      segments: [
        { ...episode.segments[0], planned_duration_seconds: 60, duration_seconds: 60 },
        { id: "host", chapter_id: "two", order: 1, kind: "NARRATION", state: "AUDIO_READY", planned_duration_seconds: 10, actual_duration_seconds: 10, audio_source_url: "/h", duration_seconds: 10, track_ref: null, title: "Host", artist: null, narration_text: "hello", asset_ref: null },
        { ...episode.segments[0], id: "second", chapter_id: "two", order: 2, title: "Second", planned_duration_seconds: 20, duration_seconds: 20 },
      ],
    };
    const plan = {
      schemaVersion: 1, episodeId: "episode-1", durationSeconds: 90,
      segmentStarts: { opening: 0, host: 60, second: 70 },
      clips: [clip("opening", "MUSIC", 0, 60), clip("host", "VOICE", 60, 10), clip("second", "MUSIC", 70, 20)],
    };

    async function mount() {
      api.get.mockResolvedValue(withHost);
      api.mixPlan.mockResolvedValue(plan);
      await act(async () => { root.render(createElement(Probe, { episodeId: "episode-1" })); });
      await flush();
    }

    it("goes from a song to the host speech after it, and records the skip", async () => {
      await mount();
      act(() => latest!.commitSeek(10));
      act(() => latest!.nextPlayback());
      expect(latest!.browserPosition).toBe(60);
      expect(api.recordUserEvent).toHaveBeenCalledWith(expect.objectContaining({ event_type: "SKIP", episode_id: "episode-1" }));
    });

    it("goes from host speech to the next song without recording a skip", async () => {
      await mount();
      act(() => latest!.commitSeek(62));
      act(() => latest!.nextPlayback());
      expect(latest!.browserPosition).toBe(70);
      expect(api.recordUserEvent).not.toHaveBeenCalledWith(expect.objectContaining({ event_type: "SKIP" }));
    });

    it("says the rest is still being prepared when nothing follows inside the prepared audio", async () => {
      await mount();
      act(() => latest!.commitSeek(80));
      act(() => latest!.nextPlayback());
      expect(latest!.browserPosition).toBe(80);
      expect(latest!.error).toBe("后面的内容还在准备中");
    });
  });

  it("persists the listener position on pause", async () => {
    await act(async () => { root.render(createElement(Probe, { episodeId: "episode-1" })); });
    await flush();
    act(() => latest!.commitSeek(42));
    act(() => latest!.pausePlayback());
    expect(latest!.browserPlaying).toBe(false);
    const stored = JSON.parse(window.localStorage.getItem("wavecast-program-progress:episode-1")!);
    expect(stored.positionSeconds).toBe(42);
    expect(api.programCheckpoint).toHaveBeenLastCalledWith("episode-1", 42);
  });

  it("takes the listener lease back when the server reports it expired", async () => {
    const { ApiRequestError } = await import("../lib/api");
    const expired = Object.assign(new ApiRequestError("listener session is inactive; resume it before generating", 409), { status: 409 });
    api.heartbeat.mockRejectedValue(expired);
    api.resume.mockResolvedValue({ ...episode, version: 2 });
    await act(async () => { root.render(createElement(Probe, { episodeId: "episode-1" })); });
    await flush();
    expect(api.resume).toHaveBeenCalledWith("episode-1");
    expect(latest?.localEpisode?.version).toBe(2);
  });

  it("does not resume an expired lease for a listener who paused", async () => {
    const { ApiRequestError } = await import("../lib/api");
    const expired = Object.assign(new ApiRequestError("listener session is inactive; resume it before generating", 409), { status: 409 });
    api.get.mockResolvedValue({ ...episode, is_playing: false });
    api.heartbeat.mockRejectedValue(expired);
    await act(async () => { root.render(createElement(Probe, { episodeId: "episode-1" })); });
    await flush();
    act(() => latest!.pausePlayback());
    await flush();
    api.resume.mockClear();
    await act(async () => { await Promise.resolve(); });
    expect(latest!.browserPlaying).toBe(false);
    expect(api.resume).not.toHaveBeenCalled();
  });
});
