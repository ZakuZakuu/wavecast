import { useSyncExternalStore } from "react";

import { api } from "./api";
import { friendlyError } from "./friendly-error";
import { watchFullVersion } from "./full-versions";
import { proposalRequest } from "./proposal-request";
import { rememberProgrammeStation, type Station, type StationId } from "./stations";
import type { DurationIntent } from "./types";
import { recordCreatedProgram, recordRecentEpisode } from "./user-library";

// 准备完整版 from the tuner: the server answers at once and makes the programme in the background, so
// the listener is free to go (even to close the app). This device keeps the requests it is still
// waiting on, asks after them while it is open, and when one is made files the programme in 节目库.
export type CreatingFullVersion = { id: string; title: string; stationId: StationId };

const PENDING_KEY = "wavecast-full-requests-v1";
/** Making a programme takes seconds; one the server no longer knows after this long is given up on. */
const GIVE_UP_MS = 2 * 60 * 1000;
const FAILURE_MS = 3200;
const STARTED_MS = 1500;
export const FULL_VERSION_REQUEST_POLL_MS = 2500;

type Pending = CreatingFullVersion & { since: number };

let pending: Pending[] = [];
let creating: CreatingFullVersion[] = [];
let loaded = false;
let starting = false;
let started = false;
let failure: string | null = null;
let failureTimer: ReturnType<typeof setTimeout> | null = null;
let startedTimer: ReturnType<typeof setTimeout> | null = null;
const NONE: CreatingFullVersion[] = [];
const listeners = new Set<() => void>();

function emit(): void {
  creating = pending.map(({ id, title, stationId }) => ({ id, title, stationId }));
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function load(): void {
  if (loaded || typeof window === "undefined") return;
  loaded = true;
  try {
    const parsed: unknown = JSON.parse(window.localStorage.getItem(PENDING_KEY) ?? "[]");
    if (Array.isArray(parsed)) {
      pending = parsed.filter((item): item is Pending => (
        typeof item?.id === "string" && typeof item?.title === "string"
        && typeof item?.stationId === "string" && typeof item?.since === "number"
      ));
      creating = pending.map(({ id, title, stationId }) => ({ id, title, stationId }));
    }
  } catch {
    // A list that cannot be read is simply not waited on.
  }
}

function save(): void {
  try {
    window.localStorage.setItem(PENDING_KEY, JSON.stringify(pending));
  } catch {
    // Without storage the request is only followed while the app stays open.
  }
  emit();
}

function briefly(set: () => void, clear: () => void, ms: number, timer: ReturnType<typeof setTimeout> | null): ReturnType<typeof setTimeout> {
  if (timer !== null) clearTimeout(timer);
  set();
  emit();
  return setTimeout(() => {
    clear();
    emit();
  }, ms);
}

function fail(text: string): void {
  failureTimer = briefly(() => { failure = text; }, () => { failure = null; }, FAILURE_MS, failureTimer);
}

/** Programmes still being made for a 完整版 (they are not in 节目库 until the server has made them). */
export function useCreatingFullVersions(): CreatingFullVersion[] {
  return useSyncExternalStore(subscribe, () => { load(); return creating; }, () => NONE);
}

/** The request is on its way to the server (the tuner's button is busy for that moment only). */
export function useFullVersionStarting(): boolean {
  return useSyncExternalStore(subscribe, () => starting, () => false);
}

/** The server has the request: the tuner's button says so for a moment. */
export function useFullVersionStarted(): boolean {
  return useSyncExternalStore(subscribe, () => started, () => false);
}

/** Why the last request did not work, for a few seconds. */
export function useFullVersionFailure(): string | null {
  return useSyncExternalStore(subscribe, () => failure, () => null);
}

export async function prepareFullVersionFromTuner(
  target: Station,
  prompt: string,
  duration: DurationIntent,
): Promise<void> {
  if (starting) return;
  load();
  starting = true;
  failure = null;
  started = false;
  emit();
  try {
    const { request_id: id } = await api.prepareFullVersion(proposalRequest(target, prompt, duration));
    pending = [...pending, { id, title: prompt.trim() || target.name, stationId: target.id, since: Date.now() }];
    save();
    startedTimer = briefly(() => { started = true; }, () => { started = false; }, STARTED_MS, startedTimer);
  } catch (reason: unknown) {
    fail(friendlyError(reason instanceof Error ? reason.message : null, "没有准备成功，再试一次"));
  } finally {
    starting = false;
    emit();
  }
}

/** Asks the server how the requests being waited on went: files the made ones, drops the failed. */
export async function settlePendingFullVersions(): Promise<void> {
  load();
  const asked = pending;
  if (!asked.length) return;
  let items;
  try {
    items = await api.fullVersionRequests(asked.map((entry) => entry.id));
  } catch {
    return;
  }
  const byId = new Map(items.map((item) => [item.request_id, item]));
  const done = new Set<string>();
  for (const entry of asked) {
    const item = byId.get(entry.id);
    if (!item) {
      // The server does not know it (it was restarted meanwhile): give up after a while.
      if (Date.now() - entry.since > GIVE_UP_MS) {
        done.add(entry.id);
        fail("没有准备成功，再试一次");
      }
    } else if (item.status === "failed") {
      done.add(entry.id);
      fail(friendlyError(item.message, "没有准备成功，再试一次"));
    } else if (item.status === "ready" && item.episode_id) {
      try {
        const episode = await api.get(item.episode_id);
        rememberProgrammeStation(episode.seed_id, entry.stationId);
        recordCreatedProgram(episode.seed_id);
        recordRecentEpisode(episode, null, 0);
        watchFullVersion({
          episodeId: episode.id,
          programmeId: episode.seed_id,
          title: episode.title ?? entry.title,
        });
        done.add(entry.id);
      } catch {
        // Asked again next time.
      }
    }
  }
  if (done.size) {
    pending = pending.filter((entry) => !done.has(entry.id));
    save();
  }
}
