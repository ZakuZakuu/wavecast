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

const NOTICE_MS = 3200;
let creating: CreatingFullVersion[] = [];
let notice: string | null = null;
let noticeTimer: ReturnType<typeof setTimeout> | null = null;
let nextId = 0;
const listeners = new Set<() => void>();

function emit(): void {
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function say(text: string): void {
  notice = text;
  if (noticeTimer !== null) clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => {
    notice = null;
    emit();
  }, NOTICE_MS);
  emit();
}

/** Programmes being made for a 完整版 right now (they are not in 节目库 until the server has made them). */
export function useCreatingFullVersions(): CreatingFullVersion[] {
  return useSyncExternalStore(subscribe, () => creating, () => creating);
}

/** The line to tell the listener about a request, wherever they are. */
export function useFullVersionNotice(): string | null {
  return useSyncExternalStore(subscribe, () => notice, () => notice);
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
  say("正在创建节目，可以离开");
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
    say("开始准备完整版");
  } catch (reason: unknown) {
    say(friendlyError(reason instanceof Error ? reason.message : null, "没有准备成功，可以再试一次"));
  } finally {
    creating = [];
    emit();
  }
}
