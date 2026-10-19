import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiRequestError } from "./api";
import type { PublicationItem } from "./types";

// A publication is made on the server (the 完整版, then one mix, then checks) while the listener is
// elsewhere. This device keeps a short list of the ones it asked for and has not yet seen finish,
// polls only while that list is not empty, and tells the listener when one can be shared.
const WATCH_KEY = "wavecast-publication-watch-v1";
const CHANGE_EVENT = "wavecast-publications-change";
/** How often the watched ones are asked about when no sheet is open. */
export const PUBLICATION_POLL_MS = 6000;
/** How often an open sheet asks, so its steps move. */
export const PUBLICATION_SHEET_POLL_MS = 2500;
/** The server gives up after 45 minutes; a watch older than that has surely ended. */
const WATCH_TTL_MS = 50 * 60 * 1000;

export type WatchedPublication = { programmeId: string; title: string; since: number };

function read(): WatchedPublication[] {
  try {
    const parsed: unknown = JSON.parse(window.localStorage.getItem(WATCH_KEY) ?? "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((item): item is WatchedPublication => (
      typeof item?.programmeId === "string" && typeof item?.title === "string" && typeof item?.since === "number"
    ));
  } catch {
    return [];
  }
}

function write(items: WatchedPublication[]): void {
  try {
    window.localStorage.setItem(WATCH_KEY, JSON.stringify(items));
  } catch {
    // Without storage the reminder is simply lost; the sheet still shows the state.
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

export function readWatchedPublications(now = Date.now()): WatchedPublication[] {
  return read().filter((item) => now - item.since < WATCH_TTL_MS);
}

export function watchPublication(item: Omit<WatchedPublication, "since">): void {
  write([...read().filter((existing) => existing.programmeId !== item.programmeId), { ...item, since: Date.now() }]);
}

export function unwatchPublication(programmeId: string): void {
  const kept = read().filter((item) => item.programmeId !== programmeId);
  if (kept.length !== read().length) write(kept);
}

export function subscribePublications(listener: () => void): () => void {
  window.addEventListener(CHANGE_EVENT, listener);
  window.addEventListener("storage", listener);
  return () => {
    window.removeEventListener(CHANGE_EVENT, listener);
    window.removeEventListener("storage", listener);
  };
}

export type FinishedPublication = WatchedPublication & { item: PublicationItem };

/**
 * Asks about everything on the watch list. Ones that can now be shared leave the list and are
 * returned, for a banner; ones that ended any other way just leave it (the sheet shows them).
 */
export async function pollWatchedPublications(): Promise<FinishedPublication[]> {
  const watched = readWatchedPublications();
  if (!watched.length) return [];
  const finished: FinishedPublication[] = [];
  const settled = new Set<string>();
  await Promise.all(watched.map(async (watch) => {
    try {
      const item = await api.programmePublication(watch.programmeId);
      if (item.status === "published") finished.push({ ...watch, item });
      if (item.status !== "preparing" && item.status !== "mixing") settled.add(watch.programmeId);
    } catch (error) {
      // The server does not know it any more; any other failure is asked about again next time.
      if (error instanceof ApiRequestError && error.status === 404) settled.add(watch.programmeId);
    }
  }));
  if (settled.size) write(read().filter((item) => !settled.has(item.programmeId)));
  return finished;
}

/** Whether a publication is still being worked on. */
export function isBeingMade(item: PublicationItem | null | undefined): boolean {
  return item?.status === "preparing" || item?.status === "mixing";
}

/**
 * The publication of one of the listener's own programmes: asked for when `enabled` turns on, and
 * again every few seconds while it is being made. `undefined` until the first answer, `null` when
 * the programme has none.
 */
export function usePublication(programmeId: string, enabled: boolean) {
  const [item, setItem] = useState<PublicationItem | null | undefined>(undefined);
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);

  const refresh = useCallback(async () => {
    try {
      const next = await api.programmePublication(programmeId);
      if (active.current) setItem(next);
    } catch (error) {
      if (!active.current) return;
      if (error instanceof ApiRequestError && error.status === 404) setItem(null);
    }
  }, [programmeId]);

  useEffect(() => {
    if (!enabled) {
      setItem(undefined);
      return;
    }
    void refresh();
  }, [enabled, refresh]);

  const making = isBeingMade(item);
  useEffect(() => {
    if (!enabled || !making) return;
    const timer = window.setInterval(() => void refresh(), PUBLICATION_SHEET_POLL_MS);
    return () => window.clearInterval(timer);
  }, [enabled, making, refresh]);

  return { item, setItem, refresh };
}
