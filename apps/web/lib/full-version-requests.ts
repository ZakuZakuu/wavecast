import { useSyncExternalStore } from "react";

import { api } from "./api";
import { friendlyError } from "./friendly-error";
import { watchFullVersion } from "./full-versions";
import { proposalRequest } from "./proposal-request";
import { rememberProgrammeStation, type Station, type StationId } from "./stations";
import type { DurationIntent } from "./types";
import { recordCreatedProgram, recordRecentEpisode } from "./user-library";

// 准备完整版 from the tuner takes a while (a programme is made, then its episode started), and the
// listener is free to leave meanwhile. So the request lives here, not in the page: whichever page they
// are on can show that it is under way, and say how it ended.
export type CreatingFullVersion = { id: string; title: string; stationId: StationId };

const FAILURE_MS = 3200;
const STARTED_MS = 1500;
let creating: CreatingFullVersion[] = [];
let failure: string | null = null;
let started = false;
let failureTimer: ReturnType<typeof setTimeout> | null = null;
let startedTimer: ReturnType<typeof setTimeout> | null = null;
let nextId = 0;
const listeners = new Set<() => void>();

function emit(): void {
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
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

/** Programmes being made for a 完整版 right now (they are not in 节目库 until the server has made them). */
export function useCreatingFullVersions(): CreatingFullVersion[] {
  return useSyncExternalStore(subscribe, () => creating, () => creating);
}

/** The last request was made: the tuner's button says so for a moment. */
export function useFullVersionStarted(): boolean {
  return useSyncExternalStore(subscribe, () => started, () => started);
}

/** Why the last request did not work, for a few seconds. */
export function useFullVersionFailure(): string | null {
  return useSyncExternalStore(subscribe, () => failure, () => failure);
}

/** Starts one; a second is not started while one is still being made. */
export async function prepareFullVersionFromTuner(
  target: Station,
  prompt: string,
  duration: DurationIntent,
): Promise<void> {
  if (creating.length) return;
  const placeholder: CreatingFullVersion = {
    id: `creating-${nextId += 1}`,
    title: prompt.trim() || target.name,
    stationId: target.id,
  };
  creating = [placeholder];
  failure = null;
  started = false;
  emit();
  try {
    const episode = await api.prepareFullVersion(proposalRequest(target, prompt, duration));
    rememberProgrammeStation(episode.seed_id, target.id);
    recordCreatedProgram(episode.seed_id);
    recordRecentEpisode(episode, null, 0);
    watchFullVersion({
      episodeId: episode.id,
      programmeId: episode.seed_id,
      title: episode.title ?? "WaveCast 节目",
    });
    startedTimer = briefly(() => { started = true; }, () => { started = false; }, STARTED_MS, startedTimer);
  } catch (reason: unknown) {
    const text = friendlyError(reason instanceof Error ? reason.message : null, "没有准备成功，再试一次");
    failureTimer = briefly(() => { failure = text; }, () => { failure = null; }, FAILURE_MS, failureTimer);
  } finally {
    creating = [];
    emit();
  }
}
