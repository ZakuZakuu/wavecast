"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../../lib/api";
import { friendlyError } from "../../lib/friendly-error";
import { watchFullVersion } from "../../lib/full-versions";
import { rememberProgrammeStation, type Station } from "../../lib/stations";
import type { DurationIntent } from "../../lib/types";
import { recordCreatedProgram, recordRecentEpisode } from "../../lib/user-library";
import { proposalRequest } from "./use-tune-start";

const NOTICE_MS = 3200;

/**
 * 准备完整版 from the tuner: the programme is tuned and its whole episode prepared in the background,
 * without playing it. It lands in 节目库 like any other programme, and the listener is told when it is done.
 */
export function usePrepareFullVersion() {
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const timer = useRef<number | null>(null);

  const say = useCallback((text: string) => {
    setNotice(text);
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setNotice(null), NOTICE_MS);
  }, []);
  useEffect(() => () => {
    if (timer.current !== null) window.clearTimeout(timer.current);
  }, []);

  const prepare = useCallback(async (target: Station, prompt: string, duration: DurationIntent) => {
    if (busy) return;
    setBusy(true);
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
      setBusy(false);
    }
  }, [busy, say]);

  return { busy, notice, prepare };
}
