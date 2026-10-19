import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("../lib/api", () => ({
  api: {
    programmePublication: vi.fn(),
    fullVersionStatuses: vi.fn(),
    publishProgramme: vi.fn(),
    revokePublication: vi.fn(),
    setPublicationVisibility: vi.fn(),
  },
  ApiRequestError: class extends Error {
    constructor(message: string, readonly status: number, readonly code?: string) { super(message); }
  },
}));
vi.mock("../components/cover/type-cover", () => ({ TypeCover: () => null }));

import { ShareSheet } from "../components/programme/share-sheet";
import { api, ApiRequestError } from "../lib/api";
import { readWatchedPublications } from "../lib/publications";
import type { PublicationItem } from "../lib/types";

const OWN = "proposal-" + "c".repeat(32);
const PUB = "pub-" + "a".repeat(32);
const target = (over: Record<string, unknown> = {}) => ({ id: OWN, title: "雨夜爵士", stationId: "night" as const, episodeId: "ep-1", ...over });

const item = (over: Partial<PublicationItem> = {}): PublicationItem => ({
  id: PUB, code: "a".repeat(10), episode_id: "ep-1", status: "published", visibility: "link", step: "done", progress: 100, ...over,
});

let root: Root;
let host: HTMLDivElement;
const written: string[] = [];

beforeEach(() => {
  window.localStorage.clear();
  written.length = 0;
  Object.defineProperty(navigator, "clipboard", { value: { writeText: (text: string) => { written.push(text); return Promise.resolve(); } }, configurable: true });
  vi.mocked(api.programmePublication).mockRejectedValue(new ApiRequestError("none", 404));
  vi.mocked(api.fullVersionStatuses).mockResolvedValue([]);
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  document.body.innerHTML = "";
  vi.clearAllMocks();
});

const mount = async (props: Record<string, unknown> = {}) => {
  await act(async () => root.render(createElement(ShareSheet, { open: true, onClose: vi.fn(), target: target(props) } as never)));
  await act(async () => { await Promise.resolve(); });
};
const text = () => document.body.querySelector(".share-sheet")?.textContent ?? "";
const button = (label: string) => [...document.body.querySelectorAll<HTMLButtonElement>(".share-sheet button")].find((node) => node.textContent?.includes(label));
const press = (label: string) => act(async () => { button(label)!.click(); });

describe("ShareSheet", () => {
  it("only hands over the link of a built-in programme: nothing is published", async () => {
    await mount({ id: "city-pop-misunderstood", episodeId: null });
    expect(text()).toContain("/program/city-pop-misunderstood");
    expect(button("复制链接")).toBeDefined();
    expect(api.publishProgramme).not.toHaveBeenCalled();
    expect(api.programmePublication).not.toHaveBeenCalled();
  });

  it("asks whether to make the 完整版 first, then starts publishing and shows the two steps", async () => {
    vi.mocked(api.publishProgramme).mockResolvedValue(item({ status: "preparing", step: "full", progress: 40 }));
    await mount({ episodeId: null });
    expect(text()).toContain("节目还没准备完整，需要准备好完整版吗？");

    await press("准备完整版");

    expect(api.publishProgramme).toHaveBeenCalledWith(OWN, "link");
    expect(text()).toContain("准备中 40%");
    expect(text()).toContain("等上一步做完");
    expect(readWatchedPublications().map((watch) => watch.programmeId)).toEqual([OWN]);
  });

  it("with the 完整版 made, asks who may listen and publishes with the choice", async () => {
    vi.mocked(api.fullVersionStatuses).mockResolvedValue([{ episode_id: "ep-1", programme_id: OWN, status: "ready", progress: 100 }]);
    vi.mocked(api.publishProgramme).mockResolvedValue(item({ status: "mixing", step: "mix", progress: 60, visibility: "public" }));
    await mount();
    expect(text()).toContain("谁能听");
    expect(text()).not.toContain("需要准备好完整版吗");

    await press("所有人");
    await press("发布");

    expect(api.publishProgramme).toHaveBeenCalledWith(OWN, "public");
    expect(text()).toContain("合成中，一般 1–2 分钟");
    expect(text()).toContain("已完成");
  });

  it("gives the link of a published programme: copyable, with who may listen and a way to stop", async () => {
    vi.mocked(api.programmePublication).mockResolvedValue(item());
    await mount();
    expect(text()).toContain("/p/" + "a".repeat(10));
    expect(text()).toContain("撤回后，新的人打不开链接");

    await press("复制链接");
    expect(written).toEqual([expect.stringContaining("/p/" + "a".repeat(10))]);
    expect(button("已复制")).toBeDefined();

    vi.mocked(api.setPublicationVisibility).mockResolvedValue(item({ visibility: "public" }));
    await act(async () => { document.body.querySelectorAll<HTMLButtonElement>(".share-sheet [role=tab]")[1].click(); });
    expect(api.setPublicationVisibility).toHaveBeenCalledWith(PUB, "public");
  });

  it("withdraws the sharing and offers to share again", async () => {
    vi.mocked(api.programmePublication).mockResolvedValue(item());
    vi.mocked(api.revokePublication).mockResolvedValue(item({ status: "revoked" }));
    await mount();

    await press("撤回分享");

    expect(api.revokePublication).toHaveBeenCalledWith(PUB);
    expect(text()).toContain("已撤回，新的人打不开链接。");
    expect(button("重新分享")).toBeDefined();
  });

  it("says what went wrong when there is no room or too many are shared, and offers a retry for a failed mix", async () => {
    vi.mocked(api.fullVersionStatuses).mockResolvedValue([{ episode_id: "ep-1", programme_id: OWN, status: "ready", progress: 100 }]);
    vi.mocked(api.publishProgramme).mockRejectedValueOnce(new ApiRequestError("最多同时分享 10 档。撤回一档之后，就能发布这一档。", 429, "limit"));
    await mount();
    await press("发布");
    expect(text()).toContain("分享的节目已经够多了");
    expect(text()).toContain("最多同时分享 10 档");

    await act(async () => root.render(createElement(ShareSheet, { open: false, onClose: vi.fn(), target: target() } as never)));
    vi.mocked(api.publishProgramme).mockRejectedValueOnce(new ApiRequestError("分享的空间暂时满了，过一会儿再试。", 503, "space"));
    await act(async () => root.render(createElement(ShareSheet, { open: true, onClose: vi.fn(), target: target() } as never)));
    await act(async () => { await Promise.resolve(); });
    await press("发布");
    expect(text()).toContain("现在发布不了");

    vi.mocked(api.programmePublication).mockResolvedValue(item({ status: "failed", step: "done", progress: 0, visibility: "public" }));
    vi.mocked(api.publishProgramme).mockResolvedValue(item({ status: "mixing", step: "mix", progress: 5 }));
    await act(async () => root.render(createElement(ShareSheet, { open: false, onClose: vi.fn(), target: target() } as never)));
    await act(async () => root.render(createElement(ShareSheet, { open: true, onClose: vi.fn(), target: target() } as never)));
    await act(async () => { await Promise.resolve(); });
    expect(text()).toContain("合成没成功");
    await press("重试");
    expect(api.publishProgramme).toHaveBeenLastCalledWith(OWN, "public");
  });

  it("is the same link for a copy of a published programme: nothing is published again", async () => {
    await mount({ id: PUB, episodeId: "copy-1" });
    expect(text()).toContain("/p/" + "a".repeat(10));
    expect(text()).toContain("直接听这一份节目");
    expect(api.publishProgramme).not.toHaveBeenCalled();
  });
});
