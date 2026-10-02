import { act, createElement, useEffect } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { LiveEpisode } from "../lib/types";

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
  leave: vi.fn(),
}));

vi.mock("../lib/api", () => ({ api, ApiRequestError: class extends Error { status = 0; } }));
vi.mock("../lib/episode-events", () => ({ subscribeToEpisodeEvents: () => () => undefined }));
vi.mock("../lib/cover/artwork", () => ({ coverArtworkUrl: async () => null }));

import { PlaybackProvider, useNowPlaying, usePlaybackControl, type NowPlaying } from "../components/player/playback-provider";
import { usePlayerStore } from "../lib/player-store";

const episode: LiveEpisode = {
  id: "episode-1", seed_id: "seed-1", listener_id: "l", version: 1, state: "STREAMING",
  generation_mode: "PROGRESSIVE", current_segment_id: null, playback_position_seconds: 0,
  is_listener_active: true, is_playing: true, program_estimated_duration_seconds: 1800,
  generated_frontier_seconds: 0, buffer_ahead_seconds: 0, committed_frontier_seconds: 0,
  timeline_duration_seconds: 0, segments: [],
};

let latest: NowPlaying | null = null;
let control: ReturnType<typeof usePlaybackControl> | null = null;

function Probe() {
  const now = useNowPlaying();
  const ctrl = usePlaybackControl();
  useEffect(() => {
    latest = now;
    control = ctrl;
  });
  return null;
}

async function flush() {
  for (let index = 0; index < 6; index += 1) {
    await act(async () => { await Promise.resolve(); });
  }
}

describe("PlaybackProvider", () => {
  let root: Root;

  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    window.localStorage.clear();
    window.sessionStorage.clear();
    usePlayerStore.setState({ episode: null });
    api.programRenderStatus.mockReturnValue(new Promise(() => undefined));
    api.programRender.mockReturnValue(new Promise(() => undefined));
    api.mixPlan.mockRejectedValue(new Error("none"));
    api.heartbeat.mockResolvedValue(episode);
    api.recordUserEvent.mockResolvedValue(undefined);
    root = createRoot(document.createElement("div"));
  });

  afterEach(() => {
    act(() => root.unmount());
    latest = null;
    control = null;
    vi.clearAllMocks();
  });

  it("publishes a failed start even though no episode exists", async () => {
    api.start.mockRejectedValue(new Error("Request failed"));
    await act(async () => { root.render(createElement(PlaybackProvider, null, createElement(Probe))); });
    expect(latest).toBeNull();
    await act(async () => control!.open({ seedId: "seed-1" }));
    await flush();
    expect(api.start).toHaveBeenCalledWith("seed-1");
    expect(latest?.target.seedId).toBe("seed-1");
    expect(latest?.localEpisode).toBeNull();
    expect(latest?.error).toBe("Request failed");

    // Retry remounts the host and starts again.
    api.start.mockResolvedValue(episode);
    await act(async () => control!.reload());
    await flush();
    expect(api.start).toHaveBeenCalledTimes(2);
    expect(latest?.localEpisode?.id).toBe("episode-1");
    expect(latest?.error).toBeNull();
  });

  it("closing a pending start prevents the late episode from playing", async () => {
    let resolveStart: (value: LiveEpisode) => void = () => undefined;
    api.start.mockReturnValue(new Promise<LiveEpisode>((resolve) => { resolveStart = resolve; }));
    await act(async () => { root.render(createElement(PlaybackProvider, null, createElement(Probe))); });
    await act(async () => control!.open({ seedId: "seed-1" }));
    await flush();
    expect(latest?.target.seedId).toBe("seed-1");

    await act(async () => control!.close({ seedId: "seed-1" }));
    await act(async () => resolveStart(episode));
    await flush();
    expect(latest).toBeNull();
    expect(usePlayerStore.getState().episode).toBeNull();
    expect(api.heartbeat).not.toHaveBeenCalled();
  });

  it("close(only) leaves a different programme playing", async () => {
    api.start.mockResolvedValue(episode);
    await act(async () => { root.render(createElement(PlaybackProvider, null, createElement(Probe))); });
    await act(async () => control!.open({ seedId: "seed-1" }));
    await flush();
    await act(async () => control!.close({ seedId: "other" }));
    await flush();
    expect(latest?.localEpisode?.id).toBe("episode-1");
  });
});
