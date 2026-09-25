import { act, createElement, useEffect, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const mocks = vi.hoisted(() => ({
  session: { data: { user: { id: "account-one" } }, isPending: false } as {
    data: { user?: { id: string } } | null;
    isPending: boolean;
  },
  getUserId: vi.fn<() => Promise<string | undefined>>(),
  merge: vi.fn<(value: unknown) => Promise<unknown>>(),
  getLibrary: vi.fn<() => Promise<unknown>>(),
  recordRecent: vi.fn<(value: unknown) => Promise<unknown>>(),
  clearToken: vi.fn(),
}));

vi.mock("../lib/auth-client", () => ({
  authClient: { useSession: () => mocks.session },
  clearApiAuthToken: mocks.clearToken,
  getApiAuthUserId: mocks.getUserId,
}));
vi.mock("../lib/api", () => ({
  api: {
    mergeMyLibrary: mocks.merge,
    myLibrary: mocks.getLibrary,
    recordLibraryRecent: mocks.recordRecent,
  },
}));

import { LibraryIdentityBridge } from "../components/library-identity-bridge";
import {
  emptyUserLibrary,
  recordCreatedProgram,
  recordRecentEpisode,
  syncAuthenticatedLibrary,
  useGuestLibraryIdentity,
} from "../lib/user-library";

function mount(node: ReactNode): { root: Root; container: HTMLDivElement } {
  const container = document.createElement("div");
  const root = createRoot(container);
  act(() => root.render(node));
  return { root, container };
}

function DirectPlayerAndTuneWrites() {
  useEffect(() => {
    recordRecentEpisode({
      id: "direct-player-episode",
      seed_id: "program-one",
      title: "Player direct entry",
      topic: "Library identity",
      playback_position_seconds: 12,
      timeline_duration_seconds: 100,
      program_estimated_duration_seconds: 100,
    } as Parameters<typeof recordRecentEpisode>[0]);
    recordCreatedProgram("direct-tune-proposal");
  }, []);
  return createElement("div", { "data-testid": "route-ready" });
}

describe("global library identity bridge", () => {
  const roots: Root[] = [];

  beforeEach(() => {
    localStorage.clear();
    useGuestLibraryIdentity();
    mocks.session = { data: { user: { id: "account-one" } }, isPending: false };
    mocks.getUserId.mockReset();
    mocks.merge.mockReset();
    mocks.getLibrary.mockReset();
    mocks.recordRecent.mockReset();
    mocks.clearToken.mockReset();
  });

  afterEach(() => {
    for (const root of roots.splice(0)) act(() => root.unmount());
  });

  it("waits for account library sync before direct Player and Tune routes can write", async () => {
    let finishMerge!: (value: unknown) => void;
    mocks.getUserId.mockResolvedValue("account-one");
    mocks.merge.mockReturnValue(new Promise((resolve) => { finishMerge = resolve; }));
    mocks.getLibrary.mockResolvedValue(emptyUserLibrary());
    mocks.recordRecent.mockReturnValue(new Promise(() => undefined));
    const { root, container } = mount(createElement(
      LibraryIdentityBridge,
      null,
      createElement(DirectPlayerAndTuneWrites),
    ));
    roots.push(root);

    await act(async () => { await Promise.resolve(); });
    expect(container.querySelector('[data-testid="route-ready"]')).toBeNull();
    expect(mocks.merge).toHaveBeenCalledTimes(1);

    await act(async () => {
      finishMerge(emptyUserLibrary());
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(container.querySelector('[data-testid="route-ready"]')).not.toBeNull();
    const accountCache = JSON.parse(
      localStorage.getItem("wavecast-user-library-v1:account:account-one") ?? "{}",
    ) as { recentPrograms?: Array<{ episodeId: string }>; createdProgramIds?: string[] };
    expect(accountCache.recentPrograms?.map((item) => item.episodeId))
      .toContain("direct-player-episode");
    expect(accountCache.createdProgramIds).toContain("direct-tune-proposal");
    expect(mocks.recordRecent).toHaveBeenCalledWith(expect.objectContaining({ episodeId: "direct-player-episode" }));
    expect(localStorage.getItem("wavecast-user-library-v1")).toBeNull();

    mocks.session = { data: null, isPending: false };
    function GuestTuneAfterTransition() {
      useEffect(() => { recordCreatedProgram("guest-after-transition"); }, []);
      return null;
    }
    await act(async () => {
      root.render(createElement(
        LibraryIdentityBridge,
        null,
        createElement(GuestTuneAfterTransition),
      ));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    const guestCache = JSON.parse(localStorage.getItem("wavecast-user-library-v1") ?? "{}");
    expect(guestCache.createdProgramIds).toContain("guest-after-transition");
    const accountAfterLogout = JSON.parse(
      localStorage.getItem("wavecast-user-library-v1:account:account-one") ?? "{}",
    );
    expect(accountAfterLogout.createdProgramIds).not.toContain("guest-after-transition");
  });

  it("switches direct routes back to guest storage after logout", async () => {
    mocks.getUserId.mockResolvedValue("account-one");
    mocks.merge.mockResolvedValue(emptyUserLibrary());
    mocks.getLibrary.mockResolvedValue(emptyUserLibrary());
    await syncAuthenticatedLibrary();

    mocks.session = { data: null, isPending: false };
    function GuestTuneWrite() {
      useEffect(() => { recordCreatedProgram("guest-after-logout"); }, []);
      return null;
    }
    const { root } = mount(createElement(
      LibraryIdentityBridge,
      null,
      createElement(GuestTuneWrite),
    ));
    roots.push(root);
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });

    const guestCache = JSON.parse(localStorage.getItem("wavecast-user-library-v1") ?? "{}");
    expect(guestCache.createdProgramIds).toContain("guest-after-logout");
    const accountCache = JSON.parse(
      localStorage.getItem("wavecast-user-library-v1:account:account-one") ?? "{}",
    );
    expect(accountCache.createdProgramIds).not.toContain("guest-after-logout");
  });
});
