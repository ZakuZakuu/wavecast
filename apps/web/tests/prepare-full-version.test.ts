import { act, createElement, type ReactElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("../lib/overlay-stack", () => ({ useOverlay: vi.fn() }));
vi.mock("../lib/api", () => ({
  api: { prepareFullVersion: vi.fn(), fullVersionRequests: vi.fn(), get: vi.fn() },
  ApiRequestError: class extends Error { constructor(message: string, readonly status: number) { super(message); } },
}));

import { MoreSheet } from "../components/player/more-sheet";
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
  // The requests live in the module (and the device's storage), so each test starts from a fresh one.
  async function fresh() {
    vi.resetModules();
    const store = await import("../lib/full-version-requests");
    function Probe() {
      const creating = store.useCreatingFullVersions();
      return createElement("div", null,
        createElement("p", { id: "creating" }, creating.map((item) => item.title).join("|")),
        createElement("p", { id: "starting" }, String(store.useFullVersionStarting())),
        createElement("p", { id: "started" }, String(store.useFullVersionStarted())),
        createElement("p", { id: "failure" }, store.useFullVersionFailure() ?? ""),
      );
    }
    await render(createElement(Probe));
    return store;
  }
  const text = (id: string) => host.querySelector(`#${id}`)?.textContent;
  const request = (id: string, status: "creating" | "ready" | "failed", extra: object = {}) =>
    ({ request_id: id, status, episode_id: null, programme_id: null, title: null, message: null, ...extra });

  it("is answered at once: the button is busy only while the server takes the request, then says it started", async () => {
    const store = await fresh();
    let accept: (value: { request_id: string }) => void = () => undefined;
    vi.mocked(api.prepareFullVersion).mockReturnValue(new Promise((done) => { accept = done; }));
    let sent: Promise<void> = Promise.resolve();
    await act(async () => { sent = store.prepareFullVersionFromTuner(STATIONS[0], "爵士", "SHORT"); });
    expect(text("starting")).toBe("true");
    expect(api.prepareFullVersion).toHaveBeenCalledWith(expect.objectContaining({ prompt: "爵士", duration_intent: "SHORT", station: STATIONS[0].id }));

    await act(async () => { accept({ request_id: "r1" }); await sent; });
    expect(text("starting")).toBe("false");
    expect(text("started")).toBe("true");
    // The programme is not made yet: it holds a place in 节目库, and is remembered on the device.
    expect(text("creating")).toBe("爵士");
    expect(window.localStorage.getItem("wavecast-full-requests-v1")).toContain("r1");

    await act(async () => { await vi.advanceTimersByTimeAsync(1600); });
    expect(text("started")).toBe("false");
    expect(text("creating")).toBe("爵士");
  });

  it("files the programme when the server has made it, and keeps waiting while it has not", async () => {
    const store = await fresh();
    vi.mocked(api.prepareFullVersion).mockResolvedValue({ request_id: "r1" });
    await act(async () => { await store.prepareFullVersionFromTuner(STATIONS[0], "爵士", "SHORT"); });

    vi.mocked(api.fullVersionRequests).mockResolvedValue([request("r1", "creating")]);
    await act(async () => { await store.settlePendingFullVersions(); });
    expect(text("creating")).toBe("爵士");
    expect(readUserLibrary().recentPrograms).toEqual([]);

    vi.mocked(api.fullVersionRequests).mockResolvedValue([request("r1", "ready", { episode_id: "ep-1", programme_id: "proposal-1" })]);
    vi.mocked(api.get).mockResolvedValue(episode);
    await act(async () => { await store.settlePendingFullVersions(); });
    expect(api.get).toHaveBeenCalledWith("ep-1");
    expect(text("creating")).toBe("");
    expect(readUserLibrary().createdProgramIds).toContain("proposal-1");
    expect(readUserLibrary().recentPrograms.map((item) => item.episodeId)).toEqual(["ep-1"]);
    expect(readWatchedFullVersions().map((item) => item.episodeId)).toEqual(["ep-1"]);
    expect(window.localStorage.getItem("wavecast-full-requests-v1")).toBe("[]");
  });

  it("is not tied to the page or the session: a request is still waited on after the app was closed", async () => {
    const store = await fresh();
    vi.mocked(api.prepareFullVersion).mockResolvedValue({ request_id: "r1" });
    await act(async () => { await store.prepareFullVersionFromTuner(STATIONS[0], "爵士", "SHORT"); });
    await act(async () => root.unmount());
    root = createRoot(host);

    const reopened = await fresh();
    expect(text("creating")).toBe("爵士");
    vi.mocked(api.fullVersionRequests).mockResolvedValue([request("r1", "ready", { episode_id: "ep-1", programme_id: "proposal-1" })]);
    vi.mocked(api.get).mockResolvedValue(episode);
    await act(async () => { await reopened.settlePendingFullVersions(); });
    expect(text("creating")).toBe("");
    expect(readUserLibrary().recentPrograms.map((item) => item.episodeId)).toEqual(["ep-1"]);
  });

  it("says why it did not work: the server's reason when it is Chinese, a plain line otherwise; and gives up on one it has lost", async () => {
    const store = await fresh();
    vi.mocked(api.prepareFullVersion).mockRejectedValueOnce(new ApiRequestError("最多同时准备 2 档", 429));
    await act(async () => { await store.prepareFullVersionFromTuner(STATIONS[0], "爵士", "SHORT"); });
    expect(text("failure")).toBe("最多同时准备 2 档");
    expect(text("creating")).toBe("");

    vi.mocked(api.prepareFullVersion).mockRejectedValueOnce(new Error("Bad gateway"));
    await act(async () => { await store.prepareFullVersionFromTuner(STATIONS[0], "爵士", "SHORT"); });
    expect(text("failure")).toBe("没有准备成功，再试一次");
    await act(async () => { await vi.advanceTimersByTimeAsync(3300); });
    expect(text("failure")).toBe("");

    // Accepted, but then the server says it failed to make the programme.
    vi.mocked(api.prepareFullVersion).mockResolvedValueOnce({ request_id: "r2" });
    await act(async () => { await store.prepareFullVersionFromTuner(STATIONS[0], "爵士", "SHORT"); });
    vi.mocked(api.fullVersionRequests).mockResolvedValue([request("r2", "failed", { message: "访客可以先创建 3 档节目。" })]);
    await act(async () => { await store.settlePendingFullVersions(); });
    expect(text("failure")).toBe("访客可以先创建 3 档节目。");
    expect(text("creating")).toBe("");

    // Accepted, and then the server forgets it (it was restarted): given up on after a couple of minutes.
    vi.mocked(api.prepareFullVersion).mockResolvedValueOnce({ request_id: "r3" });
    await act(async () => { await store.prepareFullVersionFromTuner(STATIONS[0], "爵士", "SHORT"); });
    vi.mocked(api.fullVersionRequests).mockResolvedValue([]);
    await act(async () => { await store.settlePendingFullVersions(); });
    expect(text("creating")).toBe("爵士");
    await act(async () => { await vi.advanceTimersByTimeAsync(2 * 60 * 1000 + 1000); await store.settlePendingFullVersions(); });
    expect(text("creating")).toBe("");
    expect(text("failure")).toBe("没有准备成功，再试一次");
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
