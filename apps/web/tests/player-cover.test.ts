import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PlayerCover, useLoadedCover, type LoadedCover } from "../components/player/player-cover";
import type { CoverParams } from "../lib/cover/build-cover";

const params: CoverParams = { stationId: "portrait", seed: 3, heading: "方大同\n这些年" };

let container: HTMLDivElement;
let root: Root;
let images: FakeImage[];

class FakeImage {
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  referrerPolicy = "";
  src = "";
  constructor() {
    images.push(this);
  }
}

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  images = [];
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  vi.stubGlobal("Image", FakeImage);
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

function render(song: LoadedCover, front: "song" | "show", onToggle = () => undefined) {
  act(() => root.render(createElement(PlayerCover, { params, size: 296, song, front, onToggle })));
}

describe("PlayerCover", () => {
  it("is the programme's cover alone when the song has no cover", () => {
    render({ current: null, previous: null }, "show");
    expect(container.querySelector(".player-cover")).not.toBeNull();
    expect(container.querySelector(".player-cover-stack")).toBeNull();
    expect(container.querySelector("button")).toBeNull();
  });

  it("stacks the two covers, the one in front named by the switch", () => {
    render({ current: "https://x/a.jpg", previous: null }, "song");
    const stack = container.querySelector(".player-cover-stack") as HTMLElement;
    expect(stack.dataset.front).toBe("song");
    expect(stack.querySelectorAll(".player-cover-card")).toHaveLength(2);
    const image = stack.querySelector("img") as HTMLImageElement;
    expect(image.getAttribute("src")).toBe("https://x/a.jpg");
    expect(image.getAttribute("referrerpolicy")).toBe("no-referrer");
    expect(container.querySelector("button")?.getAttribute("aria-label")).toBe("查看节目封面");

    render({ current: "https://x/a.jpg", previous: null }, "show");
    expect(container.querySelector("button")?.getAttribute("aria-label")).toBe("查看歌曲封面");
  });

  it("tells the screen when the listener taps it", () => {
    const toggle = vi.fn();
    render({ current: "https://x/a.jpg", previous: null }, "song", toggle);
    act(() => (container.querySelector("button") as HTMLButtonElement).click());
    expect(toggle).toHaveBeenCalledTimes(1);
  });

  it("keeps the previous song's cover underneath while the next one comes in", () => {
    render({ current: "https://x/b.jpg", previous: "https://x/a.jpg" }, "song");
    const sources = [...container.querySelectorAll(".is-song img")].map((node) => node.getAttribute("src"));
    expect(sources).toEqual(["https://x/a.jpg", "https://x/b.jpg"]);
  });
});

describe("useLoadedCover", () => {
  let latest: LoadedCover;
  function Probe({ src }: { src: string | null }) {
    latest = useLoadedCover(src);
    return null;
  }
  const show = (src: string | null) => act(() => root.render(createElement(Probe, { src })));

  it("offers a cover only once it has loaded", () => {
    show("https://x/a.jpg");
    expect(latest.current).toBeNull();
    act(() => images[0].onload?.());
    expect(latest.current).toBe("https://x/a.jpg");
  });

  it("drops a cover that fails to load, so the programme's cover stands alone", () => {
    show("https://x/a.jpg");
    act(() => images[0].onerror?.());
    expect(latest).toEqual({ current: null, previous: null });
  });

  it("keeps showing the last song's cover until the next one has loaded, then lets go of it", () => {
    show("https://x/a.jpg");
    act(() => images[0].onload?.());
    show("https://x/b.jpg");
    expect(latest).toEqual({ current: "https://x/a.jpg", previous: null });
    act(() => images[1].onload?.());
    expect(latest).toEqual({ current: "https://x/b.jpg", previous: "https://x/a.jpg" });
    act(() => vi.advanceTimersByTime(500));
    expect(latest).toEqual({ current: "https://x/b.jpg", previous: null });
  });

  it("shows nothing for a song without a cover", () => {
    show("https://x/a.jpg");
    act(() => images[0].onload?.());
    show(null);
    expect(latest).toEqual({ current: null, previous: null });
  });
});
