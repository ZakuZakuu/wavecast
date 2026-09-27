import { describe, expect, it, vi } from "vitest";

import {
  attachAudioLifecycle,
  syncAudioPlayback,
  type AudioElementLike,
} from "../lib/audio-player";

function fakeAudio() {
  const listeners = new Map<string, EventListener>();
  const audio: AudioElementLike & { emit: (name: string) => void } = {
    src: "",
    currentTime: 0,
    paused: true,
    load: vi.fn(),
    play: vi.fn(async () => { audio.paused = false; }),
    pause: vi.fn(() => { audio.paused = true; }),
    addEventListener: vi.fn((name, listener) => { listeners.set(name, listener); }),
    removeEventListener: vi.fn((name) => { listeners.delete(name); }),
    emit: (name) => listeners.get(name)?.(new Event(name)),
  };
  return audio;
}

describe("browser audio lifecycle", () => {
  it("loads a segment, seeks to its local position, and follows play/pause", async () => {
    const audio = fakeAudio();

    syncAudioPlayback(audio, { sourceUrl: "/audio/opening.wav", positionSeconds: 4, playing: true });
    await Promise.resolve();
    expect(audio.src).toContain("/audio/opening.wav");
    expect(audio.currentTime).toBe(4);
    expect(audio.load).toHaveBeenCalledOnce();
    expect(audio.play).toHaveBeenCalledOnce();

    audio.currentTime = 7.8;
    syncAudioPlayback(audio, { sourceUrl: audio.src, positionSeconds: 7, playing: true });
    expect(audio.currentTime).toBe(7.8);

    syncAudioPlayback(audio, { sourceUrl: audio.src, positionSeconds: 12, playing: false });
    expect(audio.currentTime).toBe(7.8);
    expect(audio.pause).toHaveBeenCalled();

    syncAudioPlayback(audio, {
      sourceUrl: audio.src,
      positionSeconds: 12,
      playing: false,
      syncPosition: true,
    });
    expect(audio.currentTime).toBe(12);
  });

  it("does not chase browser playback drift unless an explicit seek is requested", () => {
    const audio = fakeAudio();
    audio.src = "https://example.test/audio.mp3";
    audio.currentTime = 4;

    syncAudioPlayback(audio, {
      sourceUrl: audio.src,
      positionSeconds: 15,
      playing: true,
    });
    expect(audio.currentTime).toBe(4);

    syncAudioPlayback(audio, {
      sourceUrl: audio.src,
      positionSeconds: 15,
      playing: true,
      syncPosition: true,
    });
    expect(audio.currentTime).toBe(15);
  });

  it("forwards time updates and ended events and cleans up listeners", () => {
    const audio = fakeAudio();
    const onTimeUpdate = vi.fn();
    const onEnded = vi.fn();
    const onError = vi.fn();
    const cleanup = attachAudioLifecycle(audio, { onTimeUpdate, onEnded, onError });

    audio.currentTime = 3.5;
    audio.emit("timeupdate");
    audio.emit("ended");
    audio.emit("error");
    expect(onTimeUpdate).toHaveBeenCalledWith(3.5);
    expect(onEnded).toHaveBeenCalledOnce();
    expect(onError).toHaveBeenCalledOnce();

    cleanup();
    audio.emit("timeupdate");
    audio.emit("ended");
    expect(onTimeUpdate).toHaveBeenCalledOnce();
    expect(onEnded).toHaveBeenCalledOnce();
  });
});
