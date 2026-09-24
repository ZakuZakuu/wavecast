import { describe, expect, it } from "vitest";

import {
  emptyUserLibrary,
  normalizeUserLibrary,
  removeSavedFromState,
  toggleFavoriteInState,
  upsertRecentInState,
  upsertSavedInState,
  type RecentProgramRecord,
  type SavedEpisodeRecord,
} from "../lib/user-library";

function recent(overrides: Partial<RecentProgramRecord> = {}): RecentProgramRecord {
  return {
    episodeId: "episode-1",
    seedId: "seed-1",
    title: "城市入夜以后",
    topic: "City Pop",
    currentTitle: "Chapter 2",
    updatedAt: 10,
    progressSeconds: 120,
    durationSeconds: 2100,
    ...overrides,
  };
}

describe("user library state", () => {
  it("toggles proposal favorites without duplicates", () => {
    const first = toggleFavoriteInState(emptyUserLibrary(), "seed-1");
    expect(first.favoriteSeedIds).toEqual(["seed-1"]);

    const second = toggleFavoriteInState(first, "seed-1");
    expect(second.favoriteSeedIds).toEqual([]);
  });

  it("moves recently heard episodes to the front", () => {
    const first = upsertRecentInState(emptyUserLibrary(), recent());
    const second = upsertRecentInState(
      first,
      recent({ episodeId: "episode-2", updatedAt: 20 }),
    );
    const replayed = upsertRecentInState(
      second,
      recent({ episodeId: "episode-1", updatedAt: 30, progressSeconds: 360 }),
    );

    expect(replayed.recentPrograms.map((item) => item.episodeId)).toEqual([
      "episode-1",
      "episode-2",
    ]);
    expect(replayed.recentPrograms[0].progressSeconds).toBe(360);
  });

  it("upserts and removes fully saved episodes", () => {
    const saved: SavedEpisodeRecord = { ...recent(), savedAt: 50 };
    const next = upsertSavedInState(emptyUserLibrary(), saved);

    expect(next.savedEpisodes).toEqual([saved]);
    expect(removeSavedFromState(next, saved.episodeId).savedEpisodes).toEqual([]);
  });

  it("fails closed when persisted data is malformed", () => {
    expect(normalizeUserLibrary({ favoriteSeedIds: ["seed-1", "seed-1", 3] }))
      .toEqual({
        version: 1,
        favoriteSeedIds: ["seed-1"],
        recentPrograms: [],
        savedEpisodes: [],
      });
  });
});
