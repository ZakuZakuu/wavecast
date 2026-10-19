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
import { api, ApiRequestError } from "../lib/api";
import { prepareFullVersionFromTuner, useCreatingFullVersions, useFullVersionFailure, useFullVersionStarted } from "../lib/full-version-requests";
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
    const creating = useCreatingFullVersions();
    const started = useFullVersionStarted();
    const failure = useFullVersionFailure();
    return createElement("div", null,
      createElement("p", { id: "creating" }, creating.map((item) => item.title).join("|")),
      createElement("p", { id: "started" }, String(started)),
      createElement("p", { id: "failure" }, failure ?? ""),
    );
  }
  const text = (id: string) => host.querySelector(`#${id}`)?.textContent;

  it("shows at once that it is under way, files the programme when it is made, and waits for it", async () => {
    let finish: (value: LiveEpisode) => void = () => undefined;
    vi.mocked(api.prepareFullVersion).mockReturnValue(new Promise((done) => { finish = done; }));
    await render(createElement(Probe));

    let started: Promise<void> = Promise.resolve();
    await act(async () => { started = prepareFullVersionFromTuner(STATIONS[0], "爵士", "SHORT"); });
    expect(text("creating")).toBe("爵士");
    expect(text("started")).toBe("false");
    expect(api.prepareFullVersion).toHaveBeenCalledWith(expect.objectContaining({ prompt: "爵士", duration_intent: "SHORT", station: STATIONS[0].id }));

    // A second one is not started while the first is being made.
    await act(async () => { await prepareFullVersionFromTuner(STATIONS[1], "别的", "SHORT"); });
    expect(api.prepareFullVersion).toHaveBeenCalledTimes(1);

    await act(async () => { finish(episode); await started; });
    expect(text("creating")).toBe("");
    expect(text("started")).toBe("true");
    expect(readUserLibrary().createdProgramIds).toContain("proposal-1");
    expect(readUserLibrary().recentPrograms.map((item) => item.episodeId)).toEqual(["ep-1"]);
    expect(readWatchedFullVersions().map((item) => item.episodeId)).toEqual(["ep-1"]);

    await act(async () => { await vi.advanceTimersByTimeAsync(1600); });
    expect(text("started")).toBe("false");
  });

  it("is not tied to the page: it carries on and still says how it ended after the page is gone", async () => {
    let finish: (value: LiveEpisode) => void = () => undefined;
    vi.mocked(api.prepareFullVersion).mockReturnValue(new Promise((done) => { finish = done; }));
    await render(createElement(Probe));
    let started: Promise<void> = Promise.resolve();
    await act(async () => { started = prepareFullVersionFromTuner(STATIONS[0], "爵士", "SHORT"); });
    await act(async () => root.unmount());
    root = createRoot(host);
    await render(createElement(Probe));
    expect(text("creating")).toBe("爵士");
    await act(async () => { finish(episode); await started; });
    expect(text("creating")).toBe("");
    expect(text("started")).toBe("true");
  });

  it("passes on the server's reason when it is Chinese (too many at once), and a plain one otherwise", async () => {
    await render(createElement(Probe));
    vi.mocked(api.prepareFullVersion).mockRejectedValueOnce(new ApiRequestError("最多同时准备 2 档", 429));
    await act(async () => { await prepareFullVersionFromTuner(STATIONS[0], "爵士", "SHORT"); });
    expect(text("failure")).toBe("最多同时准备 2 档");
    expect(text("started")).toBe("false");
    expect(text("creating")).toBe("");
    expect(readWatchedFullVersions()).toEqual([]);

    vi.mocked(api.prepareFullVersion).mockRejectedValueOnce(new Error("Bad gateway"));
    await act(async () => { await prepareFullVersionFromTuner(STATIONS[0], "爵士", "SHORT"); });
    expect(text("failure")).toBe("没有准备成功，再试一次");
    await act(async () => { await vi.advanceTimersByTimeAsync(3300); });
    expect(text("failure")).toBe("");
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
