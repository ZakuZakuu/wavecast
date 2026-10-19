import { beforeEach, describe, expect, it, vi } from "vitest";

type Cloud = { favoriteSeedIds: string[]; recentPrograms: Array<{ episodeId: string; seedId: string; updatedAt: number }>; savedEpisodes: unknown[]; createdProgramIds: string[]; version: 1 };

const mocks = vi.hoisted(() => ({
  cloud: null as unknown as Cloud,
  gate: null as null | Promise<void>,
  calls: [] as string[],
}));
const snapshot = () => JSON.parse(JSON.stringify(mocks.cloud)) as Cloud;

vi.mock("../lib/auth-client", () => ({ getApiAuthUserId: () => Promise.resolve("account-one") }));
vi.mock("../lib/api", () => ({
  api: {
    mergeMyLibrary: () => Promise.resolve(snapshot()),
    myLibrary: () => Promise.resolve(snapshot()),
    favoriteProgram: async (id: string, enabled: boolean) => {
      mocks.calls.push(`favourite ${id} ${enabled}`);
      // A slow reply: it is the whole Library as it stood when the request was handled.
      const reply = snapshot();
      mocks.cloud.favoriteSeedIds = enabled ? [id, ...mocks.cloud.favoriteSeedIds] : mocks.cloud.favoriteSeedIds.filter((item) => item !== id);
      reply.favoriteSeedIds = mocks.cloud.favoriteSeedIds;
      if (mocks.gate) await mocks.gate;
      return reply;
    },
    removeLibraryRecent: async (id: string) => {
      mocks.calls.push(`remove ${id}`);
      mocks.cloud.recentPrograms = mocks.cloud.recentPrograms.filter((item) => item.episodeId !== id);
      return snapshot();
    },
    recordLibraryRecent: async (record: { episodeId: string; seedId: string; updatedAt: number }) => {
      mocks.calls.push(`record ${record.episodeId}`);
      mocks.cloud.recentPrograms = [record, ...mocks.cloud.recentPrograms.filter((item) => item.episodeId !== record.episodeId)];
      return snapshot();
    },
  },
}));

import {
  readUserLibrary,
  removeRecentProgramme,
  restoreRecentPrograms,
  syncAuthenticatedLibrary,
  toggleFavoriteSeed,
  useGuestLibraryIdentity,
} from "../lib/user-library";

const recent = (episodeId: string, seedId: string, updatedAt: number) => ({
  episodeId, seedId, updatedAt, title: seedId, topic: null, currentTitle: null, progressSeconds: 0, durationSeconds: 100,
});

const settled = () => vi.waitFor(() => expect(mocks.calls.length).toBeGreaterThan(0));
/** Lets every pending reply and queued write run. */
const idle = () => new Promise<void>((resolve) => setTimeout(resolve, 30));

describe("cloud library writes", () => {
  beforeEach(async () => {
    localStorage.clear();
    useGuestLibraryIdentity();
    mocks.calls.length = 0;
    mocks.gate = null;
    mocks.cloud = {
      version: 1,
      favoriteSeedIds: [],
      recentPrograms: [recent("a1", "a", 3), recent("a2", "a", 2), recent("b1", "b", 1)],
      savedEpisodes: [],
      createdProgramIds: [],
    };
    await syncAuthenticatedLibrary("account-one");
  });

  it("deleting a programme's recents removes each of its episodes in the account too", async () => {
    removeRecentProgramme("a");
    expect(readUserLibrary().recentPrograms.map((item) => item.episodeId)).toEqual(["b1"]);
    await vi.waitFor(() => expect(mocks.calls).toEqual(["remove a1", "remove a2"]));
    await vi.waitFor(() => expect(mocks.cloud.recentPrograms.map((item) => item.episodeId)).toEqual(["b1"]));
    expect(readUserLibrary().recentPrograms.map((item) => item.episodeId)).toEqual(["b1"]);
  });

  it("does not let a slower earlier reply put a deleted row back", async () => {
    let release!: () => void;
    mocks.gate = new Promise<void>((resolve) => { release = resolve; });
    // The heart's reply (still listing the row) is held back while the delete is issued.
    toggleFavoriteSeed("b");
    await settled();
    removeRecentProgramme("a");
    await idle();
    // The delete waits its turn behind the heart's write.
    expect(mocks.calls).toEqual(["favourite b true"]);
    release();
    await idle();
    expect(mocks.calls).toEqual(["favourite b true", "remove a1", "remove a2"]);
    expect(readUserLibrary().recentPrograms.map((item) => item.episodeId)).toEqual(["b1"]);
    expect(readUserLibrary().favoriteSeedIds).toEqual(["b"]);
  });

  it("puts recents back in the account when a delete is taken back", async () => {
    const removed = readUserLibrary().recentPrograms.filter((item) => item.seedId === "a");
    removeRecentProgramme("a");
    restoreRecentPrograms(removed);
    await vi.waitFor(() => expect(mocks.calls).toEqual(["remove a1", "remove a2", "record a1", "record a2"]));
    await vi.waitFor(() => expect(readUserLibrary().recentPrograms.map((item) => item.episodeId).sort()).toEqual(["a1", "a2", "b1"]));
  });
});
