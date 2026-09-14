import { create } from "zustand";

import type { LiveEpisode } from "./types";

type PlayerStore = {
  episode: LiveEpisode | null;
  setEpisode: (episode: LiveEpisode) => void;
};

export function latestEpisodeSnapshot(
  current: LiveEpisode | null,
  incoming: LiveEpisode,
): LiveEpisode {
  if (!current) return incoming;
  // A navigation to a different episode is intentional; ordering only applies
  // among snapshots for the same persisted episode.
  if (current.id !== incoming.id || current.seed_id !== incoming.seed_id) return incoming;
  return incoming.version >= current.version ? incoming : current;
}

export const usePlayerStore = create<PlayerStore>((set) => ({
  episode: null,
  setEpisode: (episode) => set((state) => {
    const latest = latestEpisodeSnapshot(state.episode, episode);
    return latest === state.episode ? state : { episode: latest };
  }),
}));
