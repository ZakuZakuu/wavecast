"use client";

import { useCallback, useSyncExternalStore } from "react";

import { isFavoriteSeed, subscribeUserLibrary, toggleFavoriteSeed } from "./user-library";

/** Whether a programme is a favourite (a heart), kept in step wherever it is shown; `toggle` returns the new state. */
export function useFavourite(seedId: string | null): { favourite: boolean; toggle: () => boolean } {
  const favourite = useSyncExternalStore(
    subscribeUserLibrary,
    () => (seedId ? isFavoriteSeed(seedId) : false),
    () => false,
  );
  const toggle = useCallback(() => (seedId ? toggleFavoriteSeed(seedId) : false), [seedId]);
  return { favourite, toggle };
}
