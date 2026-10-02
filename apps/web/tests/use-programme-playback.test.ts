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
});
