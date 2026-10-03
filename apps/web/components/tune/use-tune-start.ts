"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "../../lib/api";
import { useImmersiveOverlay } from "../../lib/chrome-visibility";
import { friendlyError } from "../../lib/friendly-error";
import { rememberCoverSource } from "../../lib/cover/programme-cover";
import { DUR } from "../../lib/motion/easing";
import { isPlaybackReadySegment } from "../../lib/playback";
import { openPlayer } from "../../lib/player-nav";
import { rememberProgrammeStation, type Station } from "../../lib/stations";
import { readLocalTaste, tasteContext } from "../../lib/taste";
import type { DurationIntent, ProgramProposal } from "../../lib/types";
import { recordCreatedProgram } from "../../lib/user-library";
import { useNowPlaying, usePlaybackControl } from "../player/playback-provider";
import type { TuningStep } from "./tuning-in";

export const LAST_STATION_KEY = "wavecast-last-station-v1";
/** 开播中 stays under the player until its fade-in (DUR.slow) has finished. */
const HANDOVER_MS = DUR.slow + 150;

type Phase =
  | { kind: "idle" }
  | {
    kind: "tuning";
    station: Station;
    label: string;
    prompt: string;
    duration: DurationIntent;
    coverId?: string;
    proposal: ProgramProposal | null;
    error: string | null;
  };

export type TuneStart = ReturnType<typeof useTuneStart>;

/**
 * The 开播 flow shared by the tuner and the home featured cards: proposal ->
 * episode start -> first playable audio -> player, with 开播中 meanwhile.
 * Nothing is requested until start() is called.
 */
export function useTuneStart() {
  const { open, close, reload } = usePlaybackControl();
  const np = useNowPlaying();
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const requestRef = useRef(0);
  const handedOver = useRef<string | null>(null);
  const [handoverAt, setHandoverAt] = useState<number | null>(null);

  useImmersiveOverlay("tuning-in", phase.kind === "tuning");

  /** `coverId`: the card the listener clicked, whose cover the programme keeps. */
  const start = useCallback(async (target: Station, prompt: string, duration: DurationIntent, coverId?: string) => {
    const requestId = requestRef.current + 1;
    requestRef.current = requestId;
    const label = prompt.trim() || target.name;
    const base = { kind: "tuning" as const, station: target, label, prompt, duration, coverId };
    handedOver.current = null;
    setPhase({ ...base, proposal: null, error: null });
    try {
      window.localStorage.setItem(LAST_STATION_KEY, target.id);
    } catch {
      // Ignore.
    }
    try {
      const batch = await api.createProgramProposals({
        prompt: prompt.trim().length >= 2 ? prompt.trim() : target.defaultTopic,
        duration_intent: duration,
        count: 1,
        taste_context: tasteContext(readLocalTaste()),
      });
      if (requestRef.current !== requestId) return;
      const proposal = batch.proposals[0];
      if (!proposal) throw new Error("没有拿到节目方案");
      rememberProgrammeStation(proposal.id, target.id);
      if (coverId) rememberCoverSource(proposal.id, coverId);
      recordCreatedProgram(proposal.id);
      setPhase({ ...base, proposal, error: null });
      open({ seedId: proposal.id });
    } catch (reason: unknown) {
      if (requestRef.current !== requestId) return;
      setPhase({
        ...base,
        proposal: null,
        error: reason instanceof Error && /[一-鿿]/.test(reason.message) ? reason.message : "开播失败了，可以再试一次",
      });
    }
  }, [open]);

  const tuningProposalId = phase.kind === "tuning" ? phase.proposal?.id ?? null : null;
  const hostEpisode = np?.localEpisode && tuningProposalId && np.localEpisode.seed_id === tuningProposalId
    ? np.localEpisode
    : null;
  const opening = useMemo(
    () => hostEpisode
      ? [...hostEpisode.segments].sort((a, b) => a.order - b.order).find((segment) => segment.kind === "MUSIC")
      : undefined,
    [hostEpisode],
  );
  const audioReady = Boolean(
    hostEpisode
    && np?.programManifest
    && np.programManifest.chunks.length > 0
    && np.programManifest.renderedFrontierSeconds > 0,
  );

  // First playable audio -> go to the player; 开播中 is done once the
  // player has faded in over it, so collapsing returns to the page.
  useEffect(() => {
    if (!audioReady || !hostEpisode || handedOver.current === hostEpisode.id) return;
    handedOver.current = hostEpisode.id;
    requestRef.current += 1;
    // 开播中 cross-fades into the player (MOTION.md §4.8).
    openPlayer(`/episode/materialized/${hostEpisode.id}`, "fade");
    setHandoverAt(Date.now());
  }, [audioReady, hostEpisode]);

  useEffect(() => {
    if (handoverAt === null) return;
    const timer = window.setTimeout(() => {
      setHandoverAt(null);
      setPhase({ kind: "idle" });
    }, HANDOVER_MS);
    return () => window.clearTimeout(timer);
  }, [handoverAt]);

  const cancel = useCallback(() => {
    requestRef.current += 1;
    if (tuningProposalId) {
      // open() may already have been called even if the episode has not
      // loaded yet: always unload this programme so a late start cannot play.
      if (hostEpisode && np) np.leaveEpisode();
      close({ seedId: tuningProposalId });
    }
    setPhase({ kind: "idle" });
  }, [close, hostEpisode, np, tuningProposalId]);

  const error = phase.kind === "tuning"
    ? phase.error ?? (hostEpisode && np?.renderState === "error" ? "节目音频暂时没有准备好" : null)
      ?? (tuningProposalId && np?.target.seedId === tuningProposalId && !hostEpisode && np.error ? friendlyError(np.error, "节目暂时无法开始，可以再试一次") : null)
    : null;

  const retry = () => {
    if (phase.kind !== "tuning") return;
    if (hostEpisode && np) {
      np.requestProgramRender();
      return;
    }
    if (phase.proposal) {
      // The proposal exists; only the episode start failed. Retry that.
      reload();
      return;
    }
    void start(phase.station, phase.prompt, phase.duration, phase.coverId);
  };

  const steps: TuningStep[] = phase.kind === "tuning" ? [
    { label: phase.proposal ? `听懂了：${phase.label}` : "正在理解你想听的", done: Boolean(phase.proposal) },
    {
      label: opening && isPlaybackReadySegment(opening)
        ? `开场歌就位：${opening.artist ? opening.artist : ""}《${opening.title}》`
        : "正在找开场歌",
      done: Boolean(opening && isPlaybackReadySegment(opening)),
    },
    { label: "正在排后面的曲目", done: audioReady },
  ] : [];

  return {
    tuning: phase.kind === "tuning" ? phase.station : null,
    start,
    cancel,
    retry,
    steps,
    error,
  };
}
