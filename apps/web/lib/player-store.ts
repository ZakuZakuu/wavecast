import { create } from "zustand";

import type { LiveEpisode } from "./types";

type PlayerStore = {
  episode: LiveEpisode | null;
  setEpisode: (episode: LiveEpisode) => void;
};

export const usePlayerStore = create<PlayerStore>((set) => ({
  episode: null,
  setEpisode: (episode) => set({ episode }),
}));
