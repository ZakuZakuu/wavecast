import { afterEach, describe, expect, it } from "vitest";

import { usePlayerStore } from "../lib/player-store";
import type { LiveEpisode } from "../lib/types";

const episode = { id: "episode", seed_id: "seed", version: 4 } as unknown as LiveEpisode;

afterEach(() => usePlayerStore.setState({ episode: null }));

describe("player episode snapshots", () => {
  it("does not let a delayed HTTP response replace a newer SSE snapshot", () => {
    const newerSnapshot = { ...episode, version: 5 };
    const delayedHttpResponse = { ...episode, version: 4 };

    usePlayerStore.getState().setEpisode(newerSnapshot);
    usePlayerStore.getState().setEpisode(delayedHttpResponse);

    expect(usePlayerStore.getState().episode).toBe(newerSnapshot);
  });

  it("allows an intentional replacement when navigation starts another episode", () => {
    const current = { ...episode, version: 5 };
    const nextEpisode = { ...episode, id: "another-episode", seed_id: "another-seed", version: 1 };

    usePlayerStore.getState().setEpisode(current);
    usePlayerStore.getState().setEpisode(nextEpisode);

    expect(usePlayerStore.getState().episode).toBe(nextEpisode);
  });
});
