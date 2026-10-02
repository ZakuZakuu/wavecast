import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProgrammeAudioPlayer } from "../components/programme-audio-player";

type Handler = ((details: MediaSessionActionDetails) => void) | null;

let handlers: Map<string, Handler>;
let metadata: unknown;
let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  handlers = new Map();
  metadata = null;
  Object.defineProperty(navigator, "mediaSession", {
    configurable: true,
    value: {
      playbackState: "none",
      setActionHandler: (action: string, handler: Handler) => handlers.set(action, handler),
      setPositionState: () => undefined,
      set metadata(value: unknown) { metadata = value; },
      get metadata() { return metadata; },
    },
  });
  (globalThis as { MediaMetadata?: unknown }).MediaMetadata = class {
    constructor(public init: Record<string, unknown>) {}
  };
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
  vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(() => undefined);
  vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(() => Promise.resolve());
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

describe("system media controls", () => {
  it("sets title, artwork, play/pause, back 15s and next track", () => {
    const calls = { play: 0, pause: 0, next: 0, seek: [] as number[] };
    act(() => {
      root.render(createElement(ProgrammeAudioPlayer, {
        streamUrl: "data:audio/mpeg;base64,",
        playing: false,
        positionSeconds: 40,
        seekToken: 0,
        renderedFrontierSeconds: 300,
        complete: false,
        title: "Merry Christmas Mr. Lawrence",
        artist: "坂本龙一",
        artwork: "blob:cover",
        onPositionChange: () => undefined,
        onEnded: () => undefined,
        onFrontierReached: () => undefined,
        onPlayRequest: () => { calls.play += 1; },
        onPauseRequest: () => { calls.pause += 1; },
        onSeekRequest: (position) => { calls.seek.push(position); },
        onNextRequest: () => { calls.next += 1; },
        onError: () => undefined,
      }));
    });

    const init = (metadata as { init: Record<string, unknown> }).init;
    expect(init.title).toBe("Merry Christmas Mr. Lawrence");
    expect(init.artist).toBe("坂本龙一");
    expect(init.artwork).toEqual([{ src: "blob:cover", sizes: "512x512", type: "image/png" }]);

    handlers.get("play")?.({ action: "play" });
    handlers.get("pause")?.({ action: "pause" });
    handlers.get("nexttrack")?.({ action: "nexttrack" });
    const audio = container.querySelector("audio")!;
    Object.defineProperty(audio, "currentTime", { configurable: true, value: 40 });
    handlers.get("seekbackward")?.({ action: "seekbackward" });
    expect(calls).toEqual({ play: 1, pause: 1, next: 1, seek: [25] });
  });
});
