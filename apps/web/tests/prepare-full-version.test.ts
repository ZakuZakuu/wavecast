import { act, createElement, type ReactElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("../lib/overlay-stack", () => ({ useOverlay: vi.fn() }));
vi.mock("../lib/api", () => ({
  api: { prepareFullVersion: vi.fn() },
  ApiRequestError: class extends Error { constructor(message: string, readonly status: number) { super(message); } },
}));

import { MoreSheet } from "../components/player/more-sheet";
import { usePrepareFullVersion } from "../components/tune/use-prepare-full-version";
import { api, ApiRequestError } from "../lib/api";
import { readWatchedFullVersions } from "../lib/full-versions";
import { STATIONS } from "../lib/stations";
import type { LiveEpisode } from "../lib/types";
import { readUserLibrary } from "../lib/user-library";

let root: Root;
let host: HTMLDivElement;
beforeEach(() => {
  window.localStorage.clear();
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
const render = (element: ReactElement) => act(async () => root.render(element));

const episode = { id: "ep-1", seed_id: "proposal-1", title: "夜里的爵士", topic: "爵士", state: "MATERIALIZING", is_listener_active: false, playback_position_seconds: 0, timeline_duration_seconds: 60, program_estimated_duration_seconds: 2100 } as unknown as LiveEpisode;

describe("准备完整版 from the tuner", () => {
  function Probe() {
    const { busy, notice, prepare } = usePrepareFullVersion();
    return createElement("div", null,
      createElement("button", { onClick: () => void prepare(STATIONS[0], "爵士", "SHORT") }, busy ? "busy" : "go"),
      createElement("p", { id: "notice" }, notice ?? ""),
    );
  }
  const press = () => act(async () => host.querySelector("button")!.click());

  it("tunes without playing, files the programme in the library, waits for it, and says it started", async () => {
    vi.mocked(api.prepareFullVersion).mockResolvedValue(episode);
    await render(createElement(Probe));
    await press();
    expect(api.prepareFullVersion).toHaveBeenCalledWith(expect.objectContaining({ prompt: "爵士", duration_intent: "SHORT", station: STATIONS[0].id }));
    expect(host.querySelector("#notice")?.textContent).toBe("开始准备完整版");
    expect(readUserLibrary().createdProgramIds).toContain("proposal-1");
    expect(readUserLibrary().recentPrograms.map((item) => item.episodeId)).toEqual(["ep-1"]);
    expect(readWatchedFullVersions().map((item) => item.episodeId)).toEqual(["ep-1"]);
  });

  it("passes on the server's reason when it is Chinese (too many at once), and a plain one otherwise", async () => {
    vi.mocked(api.prepareFullVersion).mockRejectedValueOnce(new ApiRequestError("最多同时准备 2 档", 429));
    await render(createElement(Probe));
    await press();
    expect(host.querySelector("#notice")?.textContent).toBe("最多同时准备 2 档");
    expect(readWatchedFullVersions()).toEqual([]);

    vi.mocked(api.prepareFullVersion).mockRejectedValueOnce(new Error("Bad gateway"));
    await press();
    expect(host.querySelector("#notice")?.textContent).toBe("没有准备成功，可以再试一次");
  });
});

describe("更多 menu", () => {
  const sheet = (fullVersion: "none" | "preparing" | "ready", onPrepareFull = vi.fn()) => render(createElement(MoreSheet, {
    open: true,
    onClose: vi.fn(),
    playback: { localEpisode: episode, fullVersion, exportState: "idle", exportError: null, exportArtifact: null } as never,
    onDetail: vi.fn(),
    onShare: vi.fn(),
    onPrepareFull,
  }));
  const row = (text: string) => [...document.body.querySelectorAll<HTMLButtonElement>(".action-row")].find((node) => node.textContent?.includes(text));

  it("offers 准备完整版 once, and says where it stands afterwards", async () => {
    const onPrepareFull = vi.fn();
    await sheet("none", onPrepareFull);
    expect(row("准备完整版")?.disabled).toBe(false);
    await act(async () => row("准备完整版")!.click());
    expect(onPrepareFull).toHaveBeenCalledTimes(1);
  });

  it.each([["preparing", "准备中…"], ["ready", "完整版已准备好"]] as const)("is a dead row while %s", async (state, label) => {
    await sheet(state);
    expect(row(label)?.disabled).toBe(true);
    expect(document.body.textContent).not.toContain("保存");
  });
});
