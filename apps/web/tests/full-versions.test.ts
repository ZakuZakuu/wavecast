import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("../lib/api", () => ({ api: { fullVersionStatuses: vi.fn() } }));
vi.mock("../lib/player-nav", () => ({ openPlayer: vi.fn() }));
vi.mock("../components/cover/programme-cover-view", () => ({ ProgrammeCoverView: () => null }));

import { FullVersionWatcher, useUnseenFullVersionCount } from "../components/full-version-watcher";
import { api } from "../lib/api";
import {
  clearUnseenFullVersions,
  FULL_VERSION_POLL_MS,
  playerFullVersion,
  pollWatchedFullVersions,
  readUnseenFullVersions,
  readWatchedFullVersions,
  unwatchFullVersion,
  watchFullVersion,
} from "../lib/full-versions";
import { openPlayer } from "../lib/player-nav";

const item = (id: string, status: "preparing" | "ready" | "failed" | "none") =>
  ({ episode_id: id, programme_id: `${id}-programme`, status, progress: 0 });
const watch = (id: string) => watchFullVersion({ episodeId: id, programmeId: `${id}-programme`, title: `节目 ${id}` });

beforeEach(() => {
  window.localStorage.clear();
  vi.mocked(api.fullVersionStatuses).mockReset();
  vi.mocked(openPlayer).mockClear();
});

describe("the list of 完整版 being waited for", () => {
  it("keeps what was asked for until it is seen finished, and forgets what is old", () => {
    watch("a");
    watch("b");
    watch("a");
    expect(readWatchedFullVersions().map((entry) => entry.episodeId)).toEqual(["b", "a"]);
    unwatchFullVersion("b");
    expect(readWatchedFullVersions().map((entry) => entry.episodeId)).toEqual(["a"]);
    expect(readWatchedFullVersions(Date.now() + 2 * 60 * 60 * 1000)).toEqual([]);
  });

  it("moves a finished one to the unseen list, drops a failed one, and keeps one still preparing", async () => {
    ["done", "broke", "busy", "gone"].forEach(watch);
    vi.mocked(api.fullVersionStatuses).mockResolvedValue([item("done", "ready"), item("broke", "failed"), item("busy", "preparing")]);
    const finished = await pollWatchedFullVersions();
    expect(finished.map((entry) => entry.episodeId)).toEqual(["done"]);
    expect(readWatchedFullVersions().map((entry) => entry.episodeId)).toEqual(["busy"]);
    expect(readUnseenFullVersions().map((entry) => entry.episodeId)).toEqual(["done"]);
    clearUnseenFullVersions();
    expect(readUnseenFullVersions()).toEqual([]);
  });

  it("changes nothing when the server cannot be reached, and asks nothing when nothing is waited for", async () => {
    expect(await pollWatchedFullVersions()).toEqual([]);
    expect(api.fullVersionStatuses).not.toHaveBeenCalled();
    watch("a");
    vi.mocked(api.fullVersionStatuses).mockRejectedValue(new Error("offline"));
    expect(await pollWatchedFullVersions()).toEqual([]);
    expect(readWatchedFullVersions()).toHaveLength(1);
  });
});

describe("what the player shows", () => {
  const episode = (state: string, mode: "PROGRESSIVE" | "FULL") => ({ state, generation_mode: mode }) as never;
  it("is ready once the episode is whole or was saved, preparing once asked for, otherwise nothing", () => {
    expect(playerFullVersion(null, false, false)).toBe("none");
    expect(playerFullVersion(episode("STREAMING", "PROGRESSIVE"), false, false)).toBe("none");
    expect(playerFullVersion(episode("STREAMING", "PROGRESSIVE"), false, true)).toBe("preparing");
    // Opening a programme that is being prepared elsewhere (the state may read STREAMING again once played).
    expect(playerFullVersion(episode("STREAMING", "FULL"), false, false)).toBe("preparing");
    expect(playerFullVersion(episode("MATERIALIZING", "FULL"), false, false)).toBe("preparing");
    expect(playerFullVersion(episode("MATERIALIZED", "FULL"), false, true)).toBe("ready");
    expect(playerFullVersion(episode("PUBLISHED", "FULL"), false, false)).toBe("ready");
    expect(playerFullVersion(episode("STREAMING", "PROGRESSIVE"), true, false)).toBe("ready");
  });
});

describe("FullVersionWatcher", () => {
  let root: Root;
  let host: HTMLDivElement;
  beforeEach(() => {
    vi.useFakeTimers();
    host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
  });
  afterEach(async () => {
    await act(async () => root.unmount());
    host.remove();
    vi.useRealTimers();
  });

  const mount = (hidden = false) => act(async () => {
    root.render(createElement("div", null, createElement(FullVersionWatcher, { hidden }), createElement(Dot)));
  });
  function Dot() {
    return createElement("i", { id: "dot" }, String(useUnseenFullVersionCount()));
  }

  it("polls only while something is waited for, then tells the listener with a banner that leads to the player", async () => {
    await mount();
    await act(async () => { await vi.advanceTimersByTimeAsync(FULL_VERSION_POLL_MS * 2); });
    expect(api.fullVersionStatuses).not.toHaveBeenCalled();

    vi.mocked(api.fullVersionStatuses).mockResolvedValue([item("ep-1", "ready")]);
    await act(async () => watch("ep-1"));
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(host.querySelector(".full-banner")?.textContent).toContain("节目 ep-1");
    expect(host.querySelector(".full-banner")?.textContent).toContain("完整版已准备好");
    expect(host.querySelector("#dot")?.textContent).toBe("1");

    await act(async () => host.querySelector<HTMLButtonElement>(".full-banner button")!.click());
    expect(openPlayer).toHaveBeenCalledWith("/episode/materialized/ep-1");
    expect(host.querySelector(".full-banner")).toBeNull();
  });

  it("keeps asking while it is still preparing, and shows no banner over the player", async () => {
    vi.mocked(api.fullVersionStatuses).mockResolvedValue([item("ep-2", "preparing")]);
    await mount(true);
    await act(async () => watch("ep-2"));
    await act(async () => { await vi.advanceTimersByTimeAsync(FULL_VERSION_POLL_MS * 2); });
    expect(vi.mocked(api.fullVersionStatuses).mock.calls.length).toBeGreaterThanOrEqual(3);

    vi.mocked(api.fullVersionStatuses).mockResolvedValue([item("ep-2", "ready")]);
    await act(async () => { await vi.advanceTimersByTimeAsync(FULL_VERSION_POLL_MS); });
    expect(host.querySelector(".full-banner")).toBeNull();
    expect(host.querySelector("#dot")?.textContent).toBe("1");
  });
});
