import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("next/link", () => ({ default: (props: Record<string, unknown>) => createElement("a", { ...props, href: String(props.href) }) }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ back: vi.fn(), push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(""),
}));
vi.mock("../lib/api", () => ({
  api: {
    publicProgramme: vi.fn(),
    copyPublished: vi.fn(),
    recordPublishedListen: vi.fn(() => Promise.resolve()),
    programCheckpoint: vi.fn(() => Promise.resolve({})),
  },
  ApiRequestError: class extends Error {
    constructor(message: string, readonly status: number, readonly code?: string) { super(message); }
  },
}));
vi.mock("../lib/auth-client", () => ({ authClient: { useSession: () => ({ data: null, isPending: false }) } }));
vi.mock("../lib/player-nav", () => ({ openPlayer: vi.fn() }));
vi.mock("../components/player/playback-provider", () => ({ useNowPlaying: () => null }));
vi.mock("../components/cover/type-cover", () => ({ TypeCover: () => null }));
vi.mock("../components/programme/share-sheet", () => ({ ShareSheet: () => null }));

import { ProgrammeDetailPage } from "../components/programme/programme-detail-page";
import { api, ApiRequestError } from "../lib/api";
import { openPlayer } from "../lib/player-nav";
import type { PublicProgramme } from "../lib/types";

const PUB = "pub-" + "a".repeat(32);
const published = (over: Partial<PublicProgramme> = {}): PublicProgramme => ({
  id: PUB, title: "Bossa Nova 诞生记", cover_title: null, description: "顺着它的来路听几首。",
  estimated_duration_seconds: 2100, station: "lineage", route: [], tags: [], opening_track_title: "Chega de Saudade",
  opening_track_artist: "João Gilberto", cover: { family: "f", seed: 1, palette: ["#000000", "#ffffff"] },
  is_owner: false, published: true, revoked: false, ...over,
} as PublicProgramme);

let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  window.localStorage.clear();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.clearAllMocks();
});

let remounts = 0;
const mount = async () => {
  await act(async () => root.render(createElement(ProgrammeDetailPage, { programmeId: PUB, key: ++remounts })));
  await act(async () => { await Promise.resolve(); });
};
const play = () => act(async () => { host.querySelector<HTMLButtonElement>(".pd-primary")!.click(); });

describe("a published programme's page", () => {
  it("plays as the listener's own copy: nothing is generated, and the listen is counted", async () => {
    vi.mocked(api.publicProgramme).mockResolvedValue(published());
    vi.mocked(api.copyPublished).mockResolvedValue({ id: "copy-1", seed_id: PUB } as never);
    await mount();
    expect(host.querySelector(".pd-title")?.textContent).toBe("Bossa Nova 诞生记");
    expect(host.querySelector(".pd-note")?.textContent).toContain("做好的完整节目");

    await play();

    expect(api.copyPublished).toHaveBeenCalledWith(PUB);
    expect(api.recordPublishedListen).toHaveBeenCalledWith(PUB);
    expect(openPlayer).toHaveBeenCalledWith("/episode/materialized/copy-1");
  });

  it("continues the copy the listener already has instead of making another", async () => {
    window.localStorage.setItem("wavecast-user-library-v1", JSON.stringify({
      version: 1, favoriteSeedIds: [], savedEpisodes: [], createdProgramIds: [],
      recentPrograms: [{ seedId: PUB, episodeId: "copy-1", title: "Bossa Nova 诞生记", topic: null, currentTitle: null, updatedAt: Date.now(), progressSeconds: 760, durationSeconds: 2100 }],
    }));
    vi.mocked(api.publicProgramme).mockResolvedValue(published());
    await mount();
    expect(host.querySelector(".pd-primary")?.textContent).toContain("继续播放");
    expect(host.querySelector(".pd-note")?.textContent).toContain("上次听到 12:40");

    await play();

    expect(api.copyPublished).not.toHaveBeenCalled();
    expect(openPlayer).toHaveBeenCalledWith("/episode/materialized/copy-1");
  });

  it("says the author stopped sharing, but still lets a holder of a copy listen", async () => {
    vi.mocked(api.publicProgramme).mockResolvedValue(published({ revoked: true }));
    await mount();
    expect(host.querySelector(".pd-chip")?.textContent).toBe("作者已撤回分享");
    expect(host.querySelector('[aria-label="分享这档节目"]')).toBeNull();
  });

  it("shows a page of its own for a link that is revoked, old, or was never there", async () => {
    vi.mocked(api.publicProgramme).mockRejectedValue(new ApiRequestError("revoked", 410));
    await mount();
    expect(host.querySelector("h1")?.textContent).toBe("这档节目不再分享了");

    vi.mocked(api.publicProgramme).mockRejectedValue(new ApiRequestError("legacy", 410));
    await mount();
    expect(host.querySelector("h1")?.textContent).toBe("这个链接已经失效了");
    expect(host.textContent).toContain("请让对方重新发一个新链接");

    vi.mocked(api.publicProgramme).mockRejectedValue(new ApiRequestError("Program not found", 404));
    await mount();
    expect(host.querySelector("h1")?.textContent).toBe("这档节目找不到了");
  });

  it("turns into the revoked page when the copy cannot be made because sharing was stopped meanwhile", async () => {
    vi.mocked(api.publicProgramme).mockResolvedValue(published());
    vi.mocked(api.copyPublished).mockRejectedValue(new ApiRequestError("revoked", 410));
    await mount();
    await play();
    expect(host.querySelector("h1")?.textContent).toBe("这档节目不再分享了");
    expect(openPlayer).not.toHaveBeenCalled();
  });
});
