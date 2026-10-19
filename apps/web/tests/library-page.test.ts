import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("next/link", () => ({ default: (props: Record<string, unknown>) => createElement("a", { ...props, href: String(props.href) }) }));
vi.mock("../lib/api", () => ({
  api: {
    program: vi.fn(() => Promise.resolve(null)),
    prepareFullVersion: vi.fn(),
    fullVersionStatuses: vi.fn(() => Promise.resolve([])),
    materialize: vi.fn(() => Promise.resolve({})),
  },
  ApiRequestError: class extends Error { constructor(message: string, readonly status: number) { super(message); } },
}));
vi.mock("../lib/player-nav", () => ({ openPlayer: vi.fn() }));
vi.mock("../components/cover/programme-cover-view", () => ({ ProgrammeCoverView: () => null }));

import { api } from "../lib/api";
import { LibraryPage, UNDO_MS } from "../components/library/library-page";
import { prepareFullVersionFromTuner } from "../lib/full-version-requests";
import { readUnseenFullVersions, watchFullVersion } from "../lib/full-versions";
import { STATIONS } from "../lib/stations";
import type { LiveEpisode } from "../lib/types";
import { isFavoriteSeed, readUserLibrary } from "../lib/user-library";

let root: Root;
let host: HTMLDivElement;

const record = (seedId: string, title: string, updatedAt: number) => ({
  seedId, episodeId: `${seedId}-ep`, title, topic: null, currentTitle: null, updatedAt, progressSeconds: 60, durationSeconds: 1800,
});

function seed(favorites: string[]) {
  const recent = [record("a", "雨天开车", Date.now() - 1000), record("b", "睡前半小时", Date.now() - 2000)];
  window.localStorage.setItem("wavecast-user-library-v1", JSON.stringify({
    version: 1,
    favoriteSeedIds: favorites,
    recentPrograms: recent,
    savedEpisodes: [{ ...recent[1], savedAt: Date.now() }],
    createdProgramIds: [],
  }));
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("matchMedia", () => ({ matches: true }));
  window.localStorage.clear();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const mount = () => act(async () => root.render(createElement(LibraryPage)));
const titles = () => [...host.querySelectorAll(".lib-title")].map((node) => node.textContent);
const click = (selector: string) => act(async () => host.querySelector<HTMLElement>(selector)!.click());
const press = (label: string) => act(async () => (
  [...host.querySelectorAll<HTMLButtonElement>(".lib-action")].find((button) => button.getAttribute("aria-label") === label)!.click()
));
/** The row has slid out and collapsed: the browser says its height transition ended. */
const collapsed = (rowSelector: string) => act(async () => {
  const row = host.querySelector(rowSelector)!;
  row.dispatchEvent(Object.assign(new Event("transitionend", { bubbles: true }), { propertyName: "height" }));
});

describe("LibraryPage", () => {
  it("lists recent and saved programmes with a heart on favourites and 完整版 on whole episodes", async () => {
    seed(["a"]);
    await mount();
    expect(titles()).toEqual(["雨天开车", "睡前半小时"]);
    const rows = [...host.querySelectorAll(".lib-row")];
    expect(rows[0].querySelector(".lib-heart")).not.toBeNull();
    expect(rows[0].querySelector(".lib-full")).toBeNull();
    expect(rows[1].querySelector(".lib-heart")).toBeNull();
    expect(rows[1].querySelector(".lib-full")?.textContent).toBe("完整版");
  });

  it("favourites and un-favourites from the swipe actions", async () => {
    seed([]);
    await mount();
    await press("收藏 雨天开车");
    expect(isFavoriteSeed("a")).toBe(true);
    expect(host.querySelector(".lib-heart")).not.toBeNull();
    expect(host.querySelector(".undo-toast")).toBeNull();
    await press("取消收藏 雨天开车");
    expect(isFavoriteSeed("a")).toBe(false);
  });

  it("deletes a programme (recent and saved records) and takes it back with 撤销", async () => {
    seed([]);
    await mount();
    await press("删除 睡前半小时");
    await collapsed('[data-row-key="b-ep"]');
    expect(titles()).toEqual(["雨天开车"]);
    expect(readUserLibrary().savedEpisodes).toHaveLength(0);
    expect(host.querySelector(".undo-toast")?.textContent).toContain("已删除「睡前半小时」");
    await click(".undo-toast button");
    expect(host.querySelector(".undo-toast")).toBeNull();
    expect(titles()).toEqual(["雨天开车", "睡前半小时"]);
    expect(readUserLibrary().savedEpisodes.map((item) => item.seedId)).toEqual(["b"]);
  });

  it("lets 撤销 lapse after a few seconds, and only for the last action", async () => {
    seed([]);
    await mount();
    await press("删除 雨天开车");
    await collapsed('[data-row-key="a-ep"]');
    expect(host.querySelector(".undo-toast")).not.toBeNull();
    await act(async () => { await vi.advanceTimersByTimeAsync(UNDO_MS + 100); });
    expect(host.querySelector(".undo-toast")).toBeNull();
    expect(titles()).toEqual(["睡前半小时"]);
  });

  it("shows only favourites under 收藏, and un-favouriting there can be taken back", async () => {
    seed(["b"]);
    await mount();
    const tabs = [...host.querySelectorAll<HTMLElement>('[role="tab"]')];
    await act(async () => tabs[1].click());
    expect(titles()).toEqual(["睡前半小时"]);
    await press("取消收藏 睡前半小时");
    await collapsed('[data-row-key="b-ep"]');
    expect(isFavoriteSeed("b")).toBe(false);
    expect(host.querySelector(".undo-toast")?.textContent).toContain("已取消收藏「睡前半小时」");
    expect(host.querySelector(".lib-empty")?.textContent).toContain("还没有收藏");
    await click(".undo-toast button");
    expect(isFavoriteSeed("b")).toBe(true);
    expect(titles()).toEqual(["睡前半小时"]);
  });

  describe("我调的", () => {
    const proposal = (id: string, title: string) => ({ id, title, estimated_duration_seconds: 1800 }) as never;
    const seedMine = (createdProgramIds: string[]) => {
      seed([]);
      const stored = JSON.parse(window.localStorage.getItem("wavecast-user-library-v1")!);
      window.localStorage.setItem("wavecast-user-library-v1", JSON.stringify({ ...stored, createdProgramIds }));
    };
    const openMine = async () => {
      await mount();
      await act(async () => [...host.querySelectorAll<HTMLElement>('[role="tab"]')][2].click());
    };

    it("lists a programme from its own listening record without asking the server", async () => {
      vi.mocked(api.program).mockClear();
      seedMine(["a"]);
      await openMine();
      expect(titles()).toEqual(["雨天开车"]);
      expect(api.program).not.toHaveBeenCalled();
    });

    it("still lists a programme the server no longer has, when it has been listened to", async () => {
      vi.mocked(api.program).mockRejectedValue(new Error("404"));
      seedMine(["gone", "a"]);
      await openMine();
      expect(titles()).toEqual(["雨天开车"]);
    });

    it("shows a programme that was only made, once the server describes it, and 载入 rather than 空 meanwhile", async () => {
      let resolve: (value: never) => void = () => undefined;
      vi.mocked(api.program).mockReturnValue(new Promise((done) => { resolve = done; }));
      seedMine(["fresh"]);
      await openMine();
      expect(host.querySelector(".lib-empty")?.textContent).toContain("正在载入");
      expect(host.querySelector(".lib-empty")?.textContent).not.toContain("在调频页开播");
      await act(async () => resolve(proposal("fresh", "刚调的节目")));
      expect(titles()).toEqual(["刚调的节目"]);
    });

    it("says it is empty only when there is nothing", async () => {
      vi.mocked(api.program).mockRejectedValue(new Error("404"));
      seedMine(["gone"]);
      await openMine();
      expect(titles()).toEqual([]);
      expect(host.querySelector(".lib-empty")?.textContent).toContain("在调频页开播的节目会留在这里");
    });
  });

  describe("完整版", () => {
    const fresh = (seedId: string, title: string) => ({ ...record(seedId, title, Date.now() - 1000), progressSeconds: 0 });
    const status = (episodeId: string, state: "preparing" | "ready" | "failed", progress = 0) =>
      ({ episode_id: episodeId, programme_id: episodeId.replace("-ep", ""), status: state, progress });
    const seedRecents = (...records: ReturnType<typeof fresh>[]) => window.localStorage.setItem("wavecast-user-library-v1", JSON.stringify({
      version: 1, favoriteSeedIds: [], recentPrograms: records, savedEpisodes: [], createdProgramIds: [],
    }));
    const mountAndSettle = async () => {
      await mount();
      await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    };
    const statusLines = () => [...host.querySelectorAll(".lib-status")].map((node) => node.textContent);

    it("says how far a preparing one is, that a ready one is waiting, and that a failed one failed", async () => {
      seedRecents(fresh("p", "在准备"), fresh("r", "备好了"), fresh("f", "没成功"));
      vi.mocked(api.fullVersionStatuses).mockResolvedValue([status("p-ep", "preparing", 40), status("r-ep", "ready", 100), status("f-ep", "failed")]);
      await mountAndSettle();
      expect(statusLines()).toEqual(expect.arrayContaining(["准备中 · 40%", "已准备好 · 约 30 分钟完整版", "准备失败"]));
      expect(host.querySelector('[aria-label="准备中 40%"]')).not.toBeNull();
      expect(host.querySelector(".lib-prep-line")).not.toBeNull();
      expect(host.querySelector(".lib-status.is-ready.is-new")).not.toBeNull();
    });

    it("lets a failed one be tried again, and says so when too many are being prepared", async () => {
      seedRecents(fresh("f", "没成功"));
      vi.mocked(api.fullVersionStatuses).mockResolvedValue([status("f-ep", "failed")]);
      vi.mocked(api.materialize).mockClear();
      await mountAndSettle();
      vi.mocked(api.fullVersionStatuses).mockResolvedValue([status("f-ep", "preparing")]);
      await click(".lib-retry");
      expect(api.materialize).toHaveBeenCalledWith("f-ep");
      expect(host.querySelector(".undo-toast")?.textContent).toBe("重新准备");
      expect(statusLines()[0]).toBe("准备中 · 0%");

      const { ApiRequestError } = await import("../lib/api");
      vi.mocked(api.fullVersionStatuses).mockResolvedValue([status("f-ep", "failed")]);
      vi.mocked(api.materialize).mockRejectedValueOnce(new ApiRequestError("最多同时准备 2 档", 429));
      await act(async () => { await vi.advanceTimersByTimeAsync(8100); });
      await click(".lib-retry");
      expect(host.querySelector(".undo-toast")?.textContent).toBe("最多同时准备 2 档");
    });

    it("holds a place at the top for a programme still being made, until the server has made it", async () => {
      seed([]);
      let finish: (value: LiveEpisode) => void = () => undefined;
      vi.mocked(api.prepareFullVersion).mockReturnValue(new Promise((done) => { finish = done; }));
      await mountAndSettle();
      let started: Promise<void> = Promise.resolve();
      await act(async () => { started = prepareFullVersionFromTuner(STATIONS[1], "夜里听爵士", "SHORT"); });
      const making = host.querySelector(".lib-making");
      expect(making?.textContent).toContain("夜里听爵士");
      expect(making?.textContent).toContain("正在编排");
      expect(host.querySelector(".lib-list")?.firstElementChild).toBe(making);
      await act(async () => { finish({ id: "e", seed_id: "s", title: "夜里听爵士", state: "MATERIALIZING", playback_position_seconds: 0, timeline_duration_seconds: 60, program_estimated_duration_seconds: 2100 } as LiveEpisode); await started; });
      expect(host.querySelector(".lib-making")).toBeNull();
    });

    it("counts as seen once the library is opened", async () => {
      watchFullVersion({ episodeId: "x-ep", programmeId: "x", title: "x" });
      window.localStorage.setItem("wavecast-full-unseen-v1", JSON.stringify([{ episodeId: "x-ep", programmeId: "x", title: "x", since: Date.now() }]));
      expect(readUnseenFullVersions()).toHaveLength(1);
      seed([]);
      await mountAndSettle();
      expect(readUnseenFullVersions()).toHaveLength(0);
    });
  });
});
