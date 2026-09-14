import { create } from "zustand";

import type { LiveEpisode } from "./types";

type PlayerStore = {
  episode: LiveEpisode | null;
  isPlaying: boolean;
  setEpisode: (episode: LiveEpisode) => void;
  setPlaying: (isPlaying: boolean) => void;
};

export const usePlayerStore = create<PlayerStore>((set) => ({
  episode: null,
  isPlaying: true,
  setEpisode: (episode) => set({ episode }),
  setPlaying: (isPlaying) => set({ isPlaying }),
}));
