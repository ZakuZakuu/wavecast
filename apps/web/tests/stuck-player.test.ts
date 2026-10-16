import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProgrammeAudioPlayer } from "../components/programme-audio-player";

let container: HTMLDivElement;
let root: Root;
let loads: number;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  // performance.now() is what the player measures with, so it has to follow the fake clock.
  vi.useFakeTimers({
    toFake: ["setInterval", "clearInterval", "setTimeout", "clearTimeout", "performance", "requestAnimationFrame", "cancelAnimationFrame"],
  });
  loads = 0;
  // Safari-like: native HLS, so the player owns the element directly.
  Object.defineProperty(navigator, "userAgent", {
    configurable: true,
    value: "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.7 Mobile/15E148 Safari/604.1",
  });
  vi.spyOn(HTMLMediaElement.prototype, "canPlayType").mockImplementation((type) =>
    type.includes("mpegurl") ? "maybe" : "",
  );
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
  vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(() => { loads += 1; });
  vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(() => Promise.resolve());
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

function mount(overrides: Partial<Parameters<typeof ProgrammeAudioPlayer>[0]> = {}, confirmOpeningSeek = true) {
  act(() => {
    root.render(createElement(ProgrammeAudioPlayer, {
      streamUrl: "/api/program-streams/e.m3u8",
      playing: true,
      positionSeconds: 820,
      seekToken: 0,
      renderedFrontierSeconds: 1200,
      complete: false,
      title: "t",
      onPositionChange: () => undefined,
      onEnded: () => undefined,
      onFrontierReached: () => undefined,
      onPlayRequest: () => undefined,
      onPauseRequest: () => undefined,
      onSeekRequest: () => undefined,
      onNextRequest: () => undefined,
      onError: () => undefined,
      ...overrides,
    }));
  });
  const audio = container.querySelector("audio")!;
  // A parked element: it reports a position and data, but the position never moves.
  Object.defineProperty(audio, "currentTime", { configurable: true, writable: true, value: 820 });
  Object.defineProperty(audio, "readyState", { configurable: true, value: 4 });
  Object.defineProperty(audio, "paused", { configurable: true, value: false });
  // The element confirms the opening position, as a real one does once it has data.
  if (confirmOpeningSeek) act(() => { audio.dispatchEvent(new Event("canplay")); });
  return audio;
}

describe("a player that says it is playing while nothing moves", () => {
  it("reloads the stream at the same position after the audio stops advancing, then waits before trying again", () => {
    mount();
    // Mounting itself loads the source once.
    const baseline = loads;

    act(() => { vi.advanceTimersByTime(5_000); });
    expect(loads).toBe(baseline); // not yet: a short gap is normal buffering

    act(() => { vi.advanceTimersByTime(3_000); });
    expect(loads).toBe(baseline + 1);

    act(() => { vi.advanceTimersByTime(10_000); });
    expect(loads).toBe(baseline + 1); // cool-down: a reload is itself a stall
  });

  it("reloads when the element never confirms the requested position (the seek stays pending and blocks everything)", () => {
    const audio = mount({}, false);
    const baseline = loads;
    // The listener keeps the clock moving the way a half-alive element can: audio advances, the seek never settles.
    for (let second = 0; second < 4; second += 1) {
      (audio as unknown as { currentTime: number }).currentTime += 1;
      act(() => { vi.advanceTimersByTime(1_000); });
    }
    expect(loads).toBe(baseline);

    act(() => { vi.advanceTimersByTime(2_000); });

    expect(loads).toBe(baseline + 1);
  });

  it("does not reload a player that is advancing", () => {
    const audio = mount();
    const baseline = loads;

    for (let second = 0; second < 30; second += 1) {
      (audio as unknown as { currentTime: number }).currentTime += 1;
      act(() => { vi.advanceTimersByTime(1_000); });
    }

    expect(loads).toBe(baseline);
  });

  it("does not reload while the listener has paused", () => {
    mount({ playing: false });
    const baseline = loads;

    act(() => { vi.advanceTimersByTime(60_000); });

    expect(loads).toBe(baseline);
  });

  it("does not reload when the playhead is at the end of what is published (it is only waiting)", () => {
    mount({ renderedFrontierSeconds: 824 });
    const baseline = loads;

    act(() => { vi.advanceTimersByTime(60_000); });

    expect(loads).toBe(baseline);
  });
});
