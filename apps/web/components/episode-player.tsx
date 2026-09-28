"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, ApiRequestError } from "../lib/api";
import { subscribeToEpisodeEvents } from "../lib/episode-events";
import { createEffectGenerationGuard, createSynchronizationGuard } from "../lib/episode-synchronization";
import { downloadFilename, ExportBlockedError, prepareEpisodeExport, triggerMixdownDownload, type MixdownArtifact } from "../lib/episode-export";
import { canUseArmedHandoff, formatSeconds, isPlaybackReadySegment, isProgramPlaybackComplete, isSeekAllowed, nextVisibleSegment, playbackAnchor, reconcileBrowserPosition, segmentAtPosition, segmentOffset, segmentStart, shouldArmHandoff } from "../lib/playback";
import { activeMixClipsAt, linearPositionToMixPosition, mixPlanSignature, mixPositionToLinearPosition, overlapLeadSeconds, type MixPlan } from "../lib/mix-timeline";
import { usePlayerStore } from "../lib/player-store";
import type { LiveEpisode } from "../lib/types";
import { isEpisodeSaved, recordRecentEpisode, saveMaterializedEpisode } from "../lib/user-library";
import { ChaptersSheet } from "./chapters-sheet";
import { MixAudioPlayer } from "./mix-audio-player";
import { SingleSourceAudioPlayer } from "./single-source-audio-player";
import { ProgramArtwork } from "./program-artwork";
import { WaveIcon } from "./wave-icon";

const CHAPTER_TITLES = ["开场", "夜色开始变暖", "从旋律走进城市", "另一面的节奏", "慢慢收回来"];
const HANDOFF_ARM_SECONDS = 2;
const ARRANGEMENT_ARM_SAFETY_SECONDS = 1.5;

export function EpisodePlayer({ seedId, episodeId }: { seedId?: string; episodeId?: string }) {
  const { episode, setEpisode } = usePlayerStore();
  const [error, setError] = useState<string | null>(null);
  const [browserPosition, setBrowserPosition] = useState(0);
  const [browserPlaying, setBrowserPlaying] = useState(false);
  const [mixPlan, setMixPlan] = useState<MixPlan | null>(null);
  const [masterArtifact, setMasterArtifact] = useState<MixdownArtifact | null>(null);
  const [masterActive, setMasterActive] = useState(false);
  const [masterPosition, setMasterPosition] = useState(0);
  const [masterSeekToken, setMasterSeekToken] = useState(0);
  const [masterBuffering, setMasterBuffering] = useState(false);
  const [armedSuccessorId, setArmedSuccessorId] = useState<string | null>(null);
  const [transportSegmentId, setTransportSegmentId] = useState<string | null>(null);
  const [seekToken, setSeekToken] = useState(0);
  const [seekPreview, setSeekPreview] = useState<number | null>(null);
  const [chaptersOpen, setChaptersOpen] = useState(false);
  const [exportState, setExportState] = useState<"idle" | "preparing" | "ready" | "error">("idle");
  const [exportArtifact, setExportArtifact] = useState<MixdownArtifact | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [saveState, setSaveState] = useState<"idle" | "requesting" | "preparing">("idle");
  const episodeIdRef = useRef<string | null>(null);
  const checkpointRef = useRef<number>(-1);
  const browserPositionRef = useRef(0);
  const seekPreviewRef = useRef<number | null>(null);
  const awaitingSuccessorRef = useRef(false);
  const armedSuccessorIdRef = useRef<string | null>(null);
  const armedFromSegmentIdRef = useRef<string | null>(null);
  const armedEpisodeRef = useRef<LiveEpisode | null>(null);
  const handoffAttemptRef = useRef<string | null>(null);
  const materializationRequestVersionRef = useRef<number | null>(null);
  const playbackAnchorRef = useRef<ReturnType<typeof playbackAnchor>>(null);
  const localEpisodeRef = useRef<LiveEpisode | null>(null);
  const startEffectGuardRef = useRef(createEffectGenerationGuard());
  const synchronizationGuardRef = useRef(createSynchronizationGuard());
  const handoffRequestGuardRef = useRef(createEffectGenerationGuard());
  const completionRequestGuardRef = useRef(createEffectGenerationGuard());
  const seekIntentCounterRef = useRef(0);
  const pendingSeekIntentRef = useRef<number | null>(null);
  const seekQueueRef = useRef<Promise<void>>(Promise.resolve());
  const resumeAfterSeekRef = useRef(false);
  const listenerPositionRef = useRef(0);
  const masterPositionRef = useRef(0);
  const masterActiveRef = useRef(false);
  const masterPreparationEpisodeRef = useRef<string | null>(null);
  const autoMaterializeEpisodeRef = useRef<string | null>(null);
  const mixPlanRef = useRef<MixPlan | null>(null);

  const localEpisode = episode
    && (episodeId ? episode.id === episodeId : episode.seed_id === seedId)
    ? episode
    : null;
  const serverCurrent = useMemo(
    () => localEpisode?.segments.find((segment) => segment.id === localEpisode.current_segment_id),
    [localEpisode],
  );
  const current = useMemo(
    () => {
      if (!localEpisode) return undefined;
      if (transportSegmentId) {
        const optimistic = localEpisode.segments.find(
          (segment) => segment.id === transportSegmentId,
        );
        if (optimistic) return optimistic;
      }
      return serverCurrent;
    },
    [localEpisode, serverCurrent, transportSegmentId],
  );
  const upcoming = useMemo(
    () => localEpisode && current
      ? nextVisibleSegment(localEpisode, current.id)
      : undefined,
    [current, localEpisode],
  );
  const arrangementEpisodeId = localEpisode?.id ?? null;
  const arrangementSignature = useMemo(
    () => localEpisode ? mixPlanSignature(localEpisode) : null,
    [localEpisode],
  );
  const arrangementClip = useMemo(
    () => mixPlan?.clips.find((clip) => clip.segmentId === current?.id) ?? null,
    [current?.id, mixPlan],
  );
  const upcomingArrangementClip = useMemo(
    () => mixPlan?.clips.find((clip) => clip.segmentId === upcoming?.id) ?? null,
    [mixPlan, upcoming?.id],
  );
  const transportMixPlan = arrangementClip ? mixPlan : null;
  localEpisodeRef.current = localEpisode;
  mixPlanRef.current = mixPlan;
  masterActiveRef.current = masterActive;
  masterPositionRef.current = masterPosition;

  useEffect(() => {
    setTransportSegmentId(null);
    setArmedSuccessorId(null);
    armedSuccessorIdRef.current = null;
    armedFromSegmentIdRef.current = null;
    armedEpisodeRef.current = null;
    handoffAttemptRef.current = null;
    handoffRequestGuardRef.current.start();
    completionRequestGuardRef.current.start();
    seekIntentCounterRef.current += 1;
    pendingSeekIntentRef.current = null;
    resumeAfterSeekRef.current = false;
    setMasterArtifact(null);
    setMasterActive(false);
    masterActiveRef.current = false;
    setMasterPosition(0);
    masterPositionRef.current = 0;
    setMasterSeekToken(0);
    setMasterBuffering(false);
    masterPreparationEpisodeRef.current = null;
    autoMaterializeEpisodeRef.current = null;
  }, [localEpisode?.id]);

  useEffect(() => {
    if (
      transportSegmentId
      && localEpisode?.current_segment_id === transportSegmentId
    ) {
      setTransportSegmentId(null);
    }
    const armedFrom = armedFromSegmentIdRef.current;
    if (
      armedFrom
      && localEpisode?.current_segment_id
      && localEpisode.current_segment_id !== armedFrom
    ) {
      setArmedSuccessorId(null);
      armedSuccessorIdRef.current = null;
      armedFromSegmentIdRef.current = null;
      armedEpisodeRef.current = null;
      handoffAttemptRef.current = null;
    }
  }, [localEpisode?.current_segment_id, transportSegmentId]);

  useEffect(() => {
    if (!arrangementEpisodeId || !arrangementSignature) {
      setMixPlan(null);
      return;
    }
    let cancelled = false;
    setMixPlan((currentPlan) => (
      currentPlan?.episodeId === arrangementEpisodeId ? currentPlan : null
    ));
    void api.mixPlan(arrangementEpisodeId)
      .then((plan) => {
        if (!cancelled) setMixPlan(plan);
      })
      .catch(() => {
        // Keep the previous same-Episode plan while a refreshed ready-prefix
        // arrangement is temporarily unavailable. Serial playback remains the
        // fallback when the current segment is not present in that plan.
      });
    return () => {
      cancelled = true;
    };
  }, [arrangementEpisodeId, arrangementSignature]);

  useEffect(() => {
    if (
      !localEpisode
      || !localEpisode.is_listener_active
      || localEpisode.state === "MATERIALIZING"
      || localEpisode.state === "MATERIALIZED"
      || autoMaterializeEpisodeRef.current === localEpisode.id
    ) return;

    autoMaterializeEpisodeRef.current = localEpisode.id;
    void api.materialize(localEpisode.id)
      .then((requested) => {
        const latest = localEpisodeRef.current;
        if (latest?.id === requested.id && requested.version >= latest.version) {
          setEpisode(requested);
        }
      })
      .catch(() => {
        // Full-program preparation is the preferred stable transport path, but
        // legacy progressive playback remains available if the queue is busy.
      });
  }, [
    localEpisode?.id,
    localEpisode?.is_listener_active,
    localEpisode?.state,
    setEpisode,
  ]);

  useEffect(() => {
    if (
      !localEpisode
      || localEpisode.state !== "MATERIALIZED"
      || masterArtifact
      || masterPreparationEpisodeRef.current === localEpisode.id
    ) return;

    const episodeIdAtRequest = localEpisode.id;
    masterPreparationEpisodeRef.current = episodeIdAtRequest;
    void prepareEpisodeExport(
      episodeIdAtRequest,
      {
        prepareMixdown: api.prepareMixdown,
        mixdown: api.mixdown,
      },
    )
      .then((artifact) => {
        const latest = localEpisodeRef.current;
        if (latest?.id !== episodeIdAtRequest) return;
        setMasterArtifact(artifact);
        setExportArtifact(artifact);
        setExportState("ready");

        const plan = mixPlanRef.current;
        const legacyPosition = browserPositionRef.current;
        const target = plan?.episodeId === latest.id
          ? linearPositionToMixPosition(
              latest,
              plan,
              legacyPosition,
            ).mixPositionSeconds
          : legacyPosition;
        const bounded = Math.min(
          Math.max(0, target),
          Math.max(0, artifact.durationSeconds - 0.05),
        );
        masterPositionRef.current = bounded;
        setMasterPosition(bounded);
        setMasterSeekToken((token) => token + 1);
      })
      .catch((reason: unknown) => {
        masterPreparationEpisodeRef.current = null;
        setExportState("error");
        setExportError(
          reason instanceof ExportBlockedError
            ? "完整节目音源还没有全部准备好，稍后会继续尝试。"
            : reason instanceof Error
              ? reason.message
              : "完整节目音频准备失败",
        );
      });
  }, [
    localEpisode?.id,
    localEpisode?.state,
    masterArtifact,
  ]);

  useEffect(() => {
    let mounted = true;
    const startGeneration = startEffectGuardRef.current.start();
    const deferLeave = (id: string) => {
      queueMicrotask(() => {
        if (startEffectGuardRef.current.isCurrent(startGeneration)) {
          void api.leave(id).then((left) => {
            if (startEffectGuardRef.current.isCurrent(startGeneration)) setEpisode(left);
          });
        }
      });
    };
    const leaveOnPageExit = () => {
      const currentEpisode = localEpisodeRef.current;
      if (episodeIdRef.current && currentEpisode) {
        if (!masterActiveRef.current) {
          void api.checkpoint(
            episodeIdRef.current,
            Math.floor(browserPositionRef.current),
          );
        }
        navigator.sendBeacon(`/api/episodes/${episodeIdRef.current}/leave`);
      }
    };
    window.addEventListener("pagehide", leaveOnPageExit);
    const load = episodeId ? api.get(episodeId) : api.start(seedId!);
    load.then((started) => {
      episodeIdRef.current = started.id;
      void api.recordUserEvent({
        event_type: "PLAY_START",
        program_id: started.seed_id,
        episode_id: started.id,
      }).catch(() => undefined);
      if (mounted) {
        setEpisode(started);
        setBrowserPlaying(started.is_playing && started.is_listener_active);
        setBrowserPosition(started.playback_position_seconds);
        browserPositionRef.current = started.playback_position_seconds;
        playbackAnchorRef.current = playbackAnchor(started);
      } else {
        deferLeave(started.id);
      }
    }).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "节目暂时无法开始"));
    return () => {
      mounted = false;
      window.removeEventListener("pagehide", leaveOnPageExit);
      if (episodeIdRef.current) deferLeave(episodeIdRef.current);
    };
  }, [episodeId, seedId, setEpisode]);

  useEffect(() => {
    if (!localEpisode) return;
    return subscribeToEpisodeEvents(localEpisode.id, (incoming) => {
      setEpisode(incoming);
    });
  }, [localEpisode?.id, setEpisode]);

  useEffect(() => {
    setExportState("idle");
    setExportArtifact(null);
    setExportError(null);
  }, [localEpisode?.id]);

  useEffect(() => {
    if (!localEpisode) return;
    recordRecentEpisode(localEpisode, current?.title ?? null);
    setSaved(isEpisodeSaved(localEpisode.id));
  }, [localEpisode?.id, current?.id, current?.title]);

  useEffect(() => {
    if (masterActiveRef.current) {
      playbackAnchorRef.current = playbackAnchor(localEpisode);
      return;
    }
    if (pendingSeekIntentRef.current !== null) {
      playbackAnchorRef.current = playbackAnchor(localEpisode);
      return;
    }
    const linearPosition = reconcileBrowserPosition(
      browserPositionRef.current,
      playbackAnchorRef.current,
      localEpisode,
    );
    if (seekPreviewRef.current === null) {
      setBrowserPosition(linearPosition);
      browserPositionRef.current = linearPosition;
    }
    playbackAnchorRef.current = playbackAnchor(localEpisode);
  }, [localEpisode?.current_segment_id, localEpisode?.playback_position_seconds]);

  useEffect(() => {
    if (localEpisode && !localEpisode.is_listener_active) {
      awaitingSuccessorRef.current = false;
      setBrowserPlaying(false);
    }
  }, [localEpisode?.id, localEpisode?.is_listener_active]);

  useEffect(() => {
    if (
      awaitingSuccessorRef.current
      && localEpisode?.is_listener_active
      && localEpisode.is_playing
    ) {
      awaitingSuccessorRef.current = false;
      setBrowserPlaying(true);
      setError(null);
    }
  }, [
    localEpisode?.current_segment_id,
    localEpisode?.is_listener_active,
    localEpisode?.is_playing,
  ]);

  useEffect(() => {
    if (!localEpisode?.is_listener_active) return;
    const synchronizationGuard = synchronizationGuardRef.current;
    const generation = synchronizationGuard.start();
    const heartbeat = async () => {
      if (!synchronizationGuard.isCurrent(
        generation,
        localEpisodeRef.current?.is_listener_active ?? false,
      )) return;
      try {
        await api.heartbeat(localEpisode.id);
      } catch {
        // Heartbeat is only listener-liveness metadata. Background generation is
        // backend-owned and must not interrupt browser-authoritative playback.
      }
    };

    void heartbeat();
    const heartbeatInterval = window.setInterval(() => void heartbeat(), 10_000);
    return () => {
      synchronizationGuard.invalidate();
      window.clearInterval(heartbeatInterval);
    };
  }, [localEpisode?.id, localEpisode?.is_listener_active]);

  async function update(operation: Promise<LiveEpisode>): Promise<boolean> {
    try {
      setEpisode(await operation);
      setError(null);
      return true;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "操作暂时没有完成");
      return false;
    }
  }

  const leaveEpisode = useCallback(() => {
    const currentEpisode = localEpisodeRef.current;
    if (!currentEpisode) return;
    awaitingSuccessorRef.current = false;
    setBrowserPlaying(false);
    synchronizationGuardRef.current.invalidate();
    void update(api.leave(currentEpisode.id));
  }, []);

  const completeBrowserSegment = useCallback(() => {
    if (!localEpisode || !browserPlaying || !current) return;

    const completionGeneration = completionRequestGuardRef.current.start();
    const armedId = armedSuccessorIdRef.current;
    const armedEpisode = armedEpisodeRef.current;
    const armedSegment = armedId
      ? (armedEpisode ?? localEpisode).segments.find((segment) => segment.id === armedId)
      : undefined;
    const canHandoffOptimistically = canUseArmedHandoff({
      current,
      armedSegment,
      serverCurrentId: localEpisode.current_segment_id,
      armedFromSegmentId: armedFromSegmentIdRef.current,
    });

    if (canHandoffOptimistically && armedSegment && armedEpisode) {
      const currentMixEnd = arrangementClip
        ? arrangementClip.timelineStartSeconds + arrangementClip.playableDurationSeconds
        : null;
      const nextPosition = (
        currentMixEnd !== null
        && transportMixPlan
        && upcomingArrangementClip
      )
        ? mixPositionToLinearPosition(
            armedEpisode,
            transportMixPlan,
            currentMixEnd,
          ).linearPositionSeconds
        : segmentStart(armedEpisode, armedSegment.id);
      setTransportSegmentId(armedSegment.id);
      setBrowserPosition(nextPosition);
      browserPositionRef.current = nextPosition;
      setBrowserPlaying(true);
    }

    const completion = canHandoffOptimistically && armedSegment
      ? api.completeHandoff(localEpisode.id, current.id, armedSegment.id)
      : api.completedSegment(localEpisode.id, current.id);

    void completion
      .then((completed) => {
        if (!completionRequestGuardRef.current.isCurrent(completionGeneration)) return;
        playbackAnchorRef.current = playbackAnchor(completed);
        setEpisode(completed);
        setError(null);

        if (isProgramPlaybackComplete(completed)) {
          awaitingSuccessorRef.current = false;
          setTransportSegmentId(null);
          void api.recordUserEvent({
            event_type: "PLAY_COMPLETE",
            program_id: completed.seed_id,
            episode_id: completed.id,
          }).catch(() => undefined);
          return;
        }

        if (completed.is_playing && completed.is_listener_active) {
          awaitingSuccessorRef.current = false;
          setBrowserPlaying(true);
        } else {
          awaitingSuccessorRef.current = true;
          setBrowserPlaying(false);
        }
      })
      .catch((reason: unknown) => {
        if (!completionRequestGuardRef.current.isCurrent(completionGeneration)) return;
        awaitingSuccessorRef.current = false;
        // A completion event can race with an explicit seek/manual transport
        // change. The backend rejects the stale segment identity; never let
        // that old ended event pause the newly selected source.
        if (
          reason instanceof ApiRequestError
          && reason.status === 409
          && reason.message === "completed segment is stale"
        ) {
          return;
        }
        // An armed successor is already durable, so a lost persistence response
        // must not interrupt audio that has successfully handed off locally.
        if (canHandoffOptimistically && armedSegment) {
          void api.completeHandoff(localEpisode.id, current.id, armedSegment.id)
            .then((reconciled) => {
              playbackAnchorRef.current = playbackAnchor(reconciled);
              setEpisode(reconciled);
              setBrowserPlaying(
                reconciled.is_playing && reconciled.is_listener_active,
              );
              setError(null);
            })
            .catch(() => {
              setError("播放继续中，但状态暂时没有同步");
            });
          return;
        }
        setBrowserPlaying(false);
        setError(reason instanceof Error ? reason.message : "播放状态暂时没有同步");
      });
  }, [arrangementClip, browserPlaying, current, localEpisode, setEpisode, transportMixPlan, upcomingArrangementClip]);

  const exportEpisode = useCallback(async () => {
    if (!localEpisode || localEpisode.state !== "MATERIALIZED" || exportState === "preparing") return;
    setExportState("preparing");
    setExportError(null);
    try {
      const artifact = await prepareEpisodeExport(localEpisode.id, {
        prepareMixdown: api.prepareMixdown,
        mixdown: api.mixdown,
      }, exportArtifact);
      setExportArtifact(artifact);
      setExportState("ready");
      triggerMixdownDownload(artifact, localEpisode.id);
    } catch (reason: unknown) {
      setExportState("error");
      setExportError(reason instanceof ExportBlockedError
        ? "部分音源暂时无法准备导出，请稍后重试。"
        : reason instanceof Error ? reason.message : "导出失败，请稍后重试。");
    }
  }, [exportArtifact, exportState, localEpisode]);

  const persistMaterializedEpisode = useCallback((ready: LiveEpisode) => {
    recordRecentEpisode(ready, current?.title ?? null);
    if (!saveMaterializedEpisode(ready, current?.title ?? null)) {
      throw new Error("完整节目还没有准备好");
    }
    setSaved(true);
    setError(null);
    void api.recordUserEvent({
      event_type: "SAVE",
      program_id: ready.seed_id,
      episode_id: ready.id,
    }).catch(() => undefined);
  }, [current?.title]);

  const prepareAndSaveEpisode = useCallback(async () => {
    if (!localEpisode || saveState !== "idle" || saved) return;
    if (localEpisode.state === "MATERIALIZED") {
      try {
        persistMaterializedEpisode(localEpisode);
      } catch (reason: unknown) {
        setError(reason instanceof Error ? reason.message : "保存节目失败，请稍后重试");
      }
      return;
    }

    setSaveState("requesting");
    try {
      const requested = await api.materialize(localEpisode.id);
      materializationRequestVersionRef.current = requested.version;
      setEpisode(requested);
      if (requested.state === "MATERIALIZED") {
        persistMaterializedEpisode(requested);
        setSaveState("idle");
        return;
      }
      setSaveState("preparing");
    } catch (reason: unknown) {
      materializationRequestVersionRef.current = null;
      setSaveState("idle");
      setError(reason instanceof Error ? reason.message : "完整节目生成请求失败，请稍后重试");
    }
  }, [
    localEpisode,
    persistMaterializedEpisode,
    saveState,
    saved,
    setEpisode,
  ]);

  useEffect(() => {
    if (saveState !== "preparing" || !localEpisode) return;
    if (localEpisode.state === "MATERIALIZED") {
      try {
        persistMaterializedEpisode(localEpisode);
      } catch (reason: unknown) {
        setError(reason instanceof Error ? reason.message : "保存节目失败，请稍后重试");
      } finally {
        materializationRequestVersionRef.current = null;
        setSaveState("idle");
      }
      return;
    }
    if (localEpisode.state === "MATERIALIZING") return;

    const requestedVersion = materializationRequestVersionRef.current;
    if (requestedVersion !== null && localEpisode.version > requestedVersion) {
      materializationRequestVersionRef.current = null;
      setSaveState("idle");
      setError("完整节目生成失败，可以稍后重试");
    }
  }, [localEpisode, persistMaterializedEpisode, saveState]);

  const handleAudioPosition = useCallback((segmentPosition: number) => {
    if (!localEpisode || !current || seekPreviewRef.current !== null) return;
    const position = Math.floor(
      segmentStart(localEpisode, current.id) + Math.max(0, segmentPosition),
    );
    setBrowserPosition(position);
    browserPositionRef.current = position;

    const currentDuration = current.duration_seconds
      ?? current.actual_duration_seconds
      ?? current.planned_duration_seconds;
    const remainingSeconds = Math.max(0, currentDuration - segmentPosition);
    const plannedOverlapSeconds = overlapLeadSeconds(
      arrangementClip,
      upcomingArrangementClip,
    );
    const armThresholdSeconds = Math.max(
      HANDOFF_ARM_SECONDS,
      plannedOverlapSeconds > 0
        ? plannedOverlapSeconds + ARRANGEMENT_ARM_SAFETY_SECONDS
        : HANDOFF_ARM_SECONDS,
    );
    const canArm = shouldArmHandoff({
      current,
      upcoming,
      serverCurrentId: localEpisode.current_segment_id,
      transportSegmentId,
      remainingSeconds,
      armThresholdSeconds,
    });
    if (canArm && upcoming) {
      const handoffKey = `${current.id}->${upcoming.id}`;
      if (handoffAttemptRef.current !== handoffKey) {
        handoffAttemptRef.current = handoffKey;
        const handoffGeneration = handoffRequestGuardRef.current.start();
        void api.armHandoff(localEpisode.id, upcoming.id)
          .then((armed) => {
            if (!handoffRequestGuardRef.current.isCurrent(handoffGeneration)) return;
            const latest = localEpisodeRef.current;
            if (
              latest?.id !== localEpisode.id
              || latest.current_segment_id !== current.id
            ) return;
            setArmedSuccessorId(upcoming.id);
            armedSuccessorIdRef.current = upcoming.id;
            armedFromSegmentIdRef.current = current.id;
            const effectiveEpisode = latest.version > armed.version ? latest : armed;
            armedEpisodeRef.current = effectiveEpisode;
            if (armed.version >= latest.version) {
              setEpisode(armed);
            }
          })
          .catch(() => {
            // Handoff arming is an optimization. Fall back to the conservative
            // completed->next path without surfacing a playback error.
          });
      }
    }

    if (
      position > localEpisode.playback_position_seconds
      && position % 5 === 0
      && checkpointRef.current !== position
    ) {
      checkpointRef.current = position;
      void api.checkpoint(localEpisode.id, position).catch(() => undefined);
    }
  }, [
    arrangementClip,
    current,
    localEpisode,
    setEpisode,
    transportSegmentId,
    upcoming,
    upcomingArrangementClip,
  ]);

  const handleMasterPosition = useCallback((positionSeconds: number) => {
    const bounded = Math.max(0, positionSeconds);
    masterPositionRef.current = bounded;
    setMasterPosition(bounded);
  }, []);

  const commitMasterSeek = useCallback((value: number) => {
    const artifact = masterArtifact;
    if (!artifact) return;
    const bounded = Math.min(
      Math.max(0, value),
      Math.max(0, artifact.durationSeconds - 0.05),
    );
    masterPositionRef.current = bounded;
    setMasterPosition(bounded);
    setMasterSeekToken((token) => token + 1);
    seekPreviewRef.current = null;
    setSeekPreview(null);
  }, [masterArtifact]);

  const activateMasterPlayback = useCallback(() => {
    if (!masterArtifact || masterActiveRef.current) return;

    handoffRequestGuardRef.current.start();
    completionRequestGuardRef.current.start();
    setArmedSuccessorId(null);
    armedSuccessorIdRef.current = null;
    armedFromSegmentIdRef.current = null;
    armedEpisodeRef.current = null;
    handoffAttemptRef.current = null;
    setTransportSegmentId(null);
    masterActiveRef.current = true;
    setMasterActive(true);
    setMasterBuffering(false);
    setError(null);
  }, [masterArtifact]);

  const fallbackFromMasterPlayback = useCallback(() => {
    const latest = localEpisodeRef.current;
    const plan = mixPlanRef.current;
    if (!latest || !plan || plan.episodeId !== latest.id) {
      masterActiveRef.current = false;
      setMasterActive(false);
      setBrowserPlaying(false);
      setError("完整节目音频暂时无法继续播放");
      return;
    }

    const mapped = mixPositionToLinearPosition(
      latest,
      plan,
      masterPositionRef.current,
    );
    masterActiveRef.current = false;
    setMasterActive(false);
    setMasterBuffering(false);
    setTransportSegmentId(mapped.segmentId ?? null);
    browserPositionRef.current = mapped.linearPositionSeconds;
    setBrowserPosition(mapped.linearPositionSeconds);
    setSeekToken((token) => token + 1);

    void api.seek(latest.id, Math.floor(mapped.linearPositionSeconds))
      .then((reconciled) => {
        playbackAnchorRef.current = playbackAnchor(reconciled);
        setEpisode(reconciled);
        setBrowserPlaying(
          reconciled.is_listener_active && reconciled.is_playing,
        );
        setError("完整节目音频暂时不可用，已切回兼容播放");
      })
      .catch(() => {
        setBrowserPlaying(false);
        setError("完整节目音频暂时无法继续播放");
      });
  }, [setEpisode]);

  const handleMasterEnded = useCallback(() => {
    const latest = localEpisodeRef.current;
    setBrowserPlaying(false);
    if (!latest) return;
    void api.recordUserEvent({
      event_type: "PLAY_COMPLETE",
      program_id: latest.seed_id,
      episode_id: latest.id,
    }).catch(() => undefined);
  }, []);

  const commitSeek = useCallback((value: number) => {
    if (!localEpisode) return;

    const mapped = transportMixPlan
      ? mixPositionToLinearPosition(
          localEpisode,
          transportMixPlan,
          value,
        )
      : null;
    const linearValue = mapped?.linearPositionSeconds ?? value;
    const targetSegment = (
      mapped?.segmentId
        ? localEpisode.segments.find((segment) => segment.id === mapped.segmentId)
        : segmentAtPosition(localEpisode, linearValue)
    );
    if (!isSeekAllowed(localEpisode, linearValue) || !targetSegment) {
      seekPreviewRef.current = null;
      setSeekPreview(null);
      return;
    }

    const intentId = seekIntentCounterRef.current + 1;
    seekIntentCounterRef.current = intentId;
    if (pendingSeekIntentRef.current === null) {
      resumeAfterSeekRef.current = browserPlaying;
    }
    pendingSeekIntentRef.current = intentId;

    handoffRequestGuardRef.current.start();
    completionRequestGuardRef.current.start();

    setArmedSuccessorId(null);
    armedSuccessorIdRef.current = null;
    armedFromSegmentIdRef.current = null;
    armedEpisodeRef.current = null;
    handoffAttemptRef.current = null;
    awaitingSuccessorRef.current = false;

    const activeSegmentIds = transportMixPlan
      ? new Set(
          activeMixClipsAt(transportMixPlan, value).map(
            (clip) => clip.segmentId,
          ),
        )
      : new Set<string>();
    const transitionSuccessor = nextVisibleSegment(
      localEpisode,
      targetSegment.id,
    );
    const overlapSuccessorId = (
      transitionSuccessor
      && activeSegmentIds.has(transitionSuccessor.id)
      && isPlaybackReadySegment(transitionSuccessor)
    )
      ? transitionSuccessor.id
      : null;

    setBrowserPlaying(false);
    setTransportSegmentId(targetSegment.id);
    setBrowserPosition(linearValue);
    browserPositionRef.current = linearValue;
    listenerPositionRef.current = value;
    setSeekToken((token) => token + 1);
    seekPreviewRef.current = null;
    setSeekPreview(null);

    const episodeIdAtIntent = localEpisode.id;
    const targetSegmentId = targetSegment.id;
    seekQueueRef.current = seekQueueRef.current
      .catch(() => undefined)
      .then(async () => {
        if (intentId !== seekIntentCounterRef.current) return;

        let response: LiveEpisode;
        try {
          response = await api.seek(
            episodeIdAtIntent,
            Math.floor(linearValue),
          );
        } catch (reason: unknown) {
          if (intentId !== seekIntentCounterRef.current) return;
          pendingSeekIntentRef.current = null;
          const latest = localEpisodeRef.current;
          if (latest?.id === episodeIdAtIntent) {
            setTransportSegmentId(null);
            setBrowserPosition(latest.playback_position_seconds);
            browserPositionRef.current = latest.playback_position_seconds;
            setSeekToken((token) => token + 1);
            setBrowserPlaying(
              resumeAfterSeekRef.current
              && latest.is_playing
              && latest.is_listener_active,
            );
          }
          resumeAfterSeekRef.current = false;
          setError(
            reason instanceof Error ? reason.message : "跳转暂时没有完成",
          );
          return;
        }

        if (intentId !== seekIntentCounterRef.current) return;
        playbackAnchorRef.current = playbackAnchor(response);
        setEpisode(response);

        let effectiveEpisode = response;
        if (
          overlapSuccessorId
          && response.current_segment_id === targetSegmentId
        ) {
          try {
            const armed = await api.armHandoff(
              episodeIdAtIntent,
              overlapSuccessorId,
            );
            if (intentId !== seekIntentCounterRef.current) return;
            effectiveEpisode = armed;
            setArmedSuccessorId(overlapSuccessorId);
            armedSuccessorIdRef.current = overlapSuccessorId;
            armedFromSegmentIdRef.current = targetSegmentId;
            armedEpisodeRef.current = armed;
            setEpisode(armed);
          } catch {
            // Serial playback from the requested source is still valid.
          }
        }

        if (intentId !== seekIntentCounterRef.current) return;
        pendingSeekIntentRef.current = null;
        setBrowserPosition(linearValue);
        browserPositionRef.current = linearValue;
        setError(null);
        setBrowserPlaying(
          resumeAfterSeekRef.current
          && effectiveEpisode.is_playing
          && effectiveEpisode.is_listener_active,
        );
        resumeAfterSeekRef.current = false;
      });
  }, [
    browserPlaying,
    localEpisode,
    setEpisode,
    transportMixPlan,
  ]);

  const commitSeekPreview = useCallback(() => {
    const preview = seekPreviewRef.current;
    if (preview === null) return;
    // Pointer-up is commonly followed by blur. Clear synchronously so one drag
    // cannot accidentally issue two seek requests.
    seekPreviewRef.current = null;
    setSeekPreview(null);
    if (masterActiveRef.current) {
      commitMasterSeek(preview);
      return;
    }
    commitSeek(preview);
  }, [commitMasterSeek, commitSeek]);

  const pausePlayback = useCallback(() => {
    if (!localEpisode) return;
    awaitingSuccessorRef.current = false;
    setBrowserPlaying(false);
    if (masterActiveRef.current) {
      return;
    }
    const position = Math.floor(browserPositionRef.current);
    void api.checkpoint(localEpisode.id, position)
      .then(() => api.pause(localEpisode.id))
      .then((paused) => {
        playbackAnchorRef.current = playbackAnchor(paused);
        setEpisode(paused);
        setError(null);
      })
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : "暂停状态暂时没有同步");
      });
  }, [localEpisode, setEpisode]);

  const resumePlayback = useCallback(() => {
    if (!localEpisode) return;
    awaitingSuccessorRef.current = false;
    setBrowserPlaying(true);
    if (masterActiveRef.current && localEpisode.is_listener_active) {
      setError(null);
      return;
    }
    void api.resume(localEpisode.id)
      .then((resumed) => {
        playbackAnchorRef.current = playbackAnchor(resumed);
        setEpisode(resumed);
        setError(null);
      })
      .catch((reason: unknown) => {
        // Browser playback is deliberately authoritative. A persistence race
        // must not make the play button feel broken.
        setError(reason instanceof Error ? reason.message : "播放状态暂时没有同步");
      });
  }, [localEpisode, setEpisode]);

  if (error && !localEpisode) {
    return (
      <main className="player-state">
        <Link href="/" className="round-back"><WaveIcon name="back" /></Link>
        <p>{error}</p>
      </main>
    );
  }
  if (!localEpisode) {
    return (
      <main className="player-state">
        <div className="tuning-orb"><i /><i /><i /></div>
        <h1>正在接入节目…</h1>
        <p>音乐会先开始，接下来的内容在路上。</p>
      </main>
    );
  }

  const masterMode = masterActive && masterArtifact !== null;

  const displayedLinearPosition = browserPosition;
  const legacyListenerPosition = transportMixPlan
    ? linearPositionToMixPosition(
        localEpisode,
        transportMixPlan,
        displayedLinearPosition,
      ).mixPositionSeconds
    : displayedLinearPosition;
  const legacyMaxSeekPosition = transportMixPlan?.durationSeconds
    ?? localEpisode.generated_frontier_seconds;
  const arrangementCompression = transportMixPlan
    ? Math.max(
        0,
        localEpisode.generated_frontier_seconds
          - transportMixPlan.durationSeconds,
      )
    : 0;
  const legacyFullDuration = Math.max(
    legacyMaxSeekPosition,
    localEpisode.timeline_duration_seconds - arrangementCompression,
  );

  const maxSeekPosition = masterMode
    ? masterArtifact.durationSeconds
    : legacyMaxSeekPosition;
  const fullDuration = masterMode
    ? masterArtifact.durationSeconds
    : legacyFullDuration;
  const generatedPercent = masterMode
    ? 100
    : Math.min(
        100,
        Math.round((maxSeekPosition / Math.max(1, fullDuration)) * 100),
      );
  const displayedPosition = seekPreview ?? (
    masterMode ? masterPosition : legacyListenerPosition
  );

  const activeMasterClips = masterMode && mixPlan
    ? activeMixClipsAt(mixPlan, masterPosition)
    : [];
  const displayMasterClip = activeMasterClips.find(
    (clip) => clip.lane === "VOICE",
  ) ?? activeMasterClips[activeMasterClips.length - 1];
  const displayCurrent = displayMasterClip
    ? localEpisode.segments.find(
        (segment) => segment.id === displayMasterClip.segmentId,
      ) ?? current
    : current;

  const currentOffset = current
    ? segmentOffset(localEpisode, current.id, displayedLinearPosition)
    : 0;
  const seekPreviewLinearPosition = (
    !masterMode
    && seekPreview !== null
    && transportMixPlan
  )
    ? mixPositionToLinearPosition(
        localEpisode,
        transportMixPlan,
        seekPreview,
      ).linearPositionSeconds
    : seekPreview;
  const seekPreviewTarget = !masterMode && seekPreviewLinearPosition !== null
    ? segmentAtPosition(localEpisode, seekPreviewLinearPosition)
    : undefined;
  const preloadTarget = (
    seekPreviewTarget
    && seekPreviewTarget.id !== current?.id
    && isPlaybackReadySegment(seekPreviewTarget)
  )
    ? seekPreviewTarget
    : upcoming;
  const preloadSourceUrl = isPlaybackReadySegment(preloadTarget)
    ? preloadTarget?.audio_source_url ?? null
    : null;
  const chapterIds = Array.from(
    new Set(localEpisode.segments.map((segment) => segment.chapter_id)),
  );
  const currentChapterIndex = Math.max(
    0,
    chapterIds.indexOf(displayCurrent?.chapter_id ?? chapterIds[0]),
  );
  const chapterTitle = CHAPTER_TITLES[currentChapterIndex]
    ?? "Chapter " + (currentChapterIndex + 1);
  const remaining = Math.max(0, fullDuration - displayedPosition);
  const preparingAhead = masterMode
    ? false
    : (
        localEpisode.state !== "MATERIALIZED"
        && localEpisode.buffer_ahead_seconds < 45
      );

  const nextPlayback = async () => {
    if (masterMode && mixPlan) {
      const nextStart = Object.values(mixPlan.segmentStarts)
        .filter((start) => start > masterPosition + 0.5)
        .sort((left, right) => left - right)[0];
      if (typeof nextStart === "number") {
        commitMasterSeek(nextStart);
        void api.recordUserEvent({
          event_type: "SKIP",
          program_id: localEpisode.seed_id,
          episode_id: localEpisode.id,
        }).catch(() => undefined);
      }
      return;
    }

    const runNext = async () => {
      const response = await api.next(localEpisode.id);
      setEpisode(response);
      setError(null);
      void api.recordUserEvent({
        event_type: "SKIP",
        program_id: response.seed_id,
        episode_id: response.id,
      }).catch(() => undefined);
    };
    try {
      await runNext();
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "下一章节还没有准备好");
    }
  };

  listenerPositionRef.current = displayedPosition;

  const nudgeSeek = (seconds: number) => {
    const target = Math.max(0, listenerPositionRef.current + seconds);
    if (masterMode) {
      commitMasterSeek(target);
      return;
    }
    commitSeek(target);
  };

  return (
    <main className="now-playing-page page-enter">
      {masterArtifact ? (
        <SingleSourceAudioPlayer
          audioUrl={masterArtifact.audioUrl}
          playing={
            masterActive
            && browserPlaying
            && localEpisode.is_listener_active
          }
          positionSeconds={masterPosition}
          seekToken={masterSeekToken}
          title={localEpisode.title ?? "WaveCast"}
          subtitle={displayCurrent?.kind === "MUSIC"
            ? [displayCurrent.artist, displayCurrent.title].filter(Boolean).join(" — ")
            : displayCurrent?.title ?? "WaveCast"}
          onPositionChange={handleMasterPosition}
          onPlayRequest={resumePlayback}
          onPauseRequest={pausePlayback}
          onSeekRequest={commitMasterSeek}
          onBufferingChange={setMasterBuffering}
          onReady={activateMasterPlayback}
          onEnded={handleMasterEnded}
          onError={fallbackFromMasterPlayback}
        />
      ) : null}

      {!masterMode ? (
        <MixAudioPlayer
          segment={current}
          upcomingSegment={upcoming}
          plan={mixPlan}
          playing={browserPlaying && localEpisode.is_listener_active}
          positionSeconds={currentOffset}
          seekToken={seekToken}
          armedSuccessorId={armedSuccessorId}
          preloadSourceUrl={preloadSourceUrl}
          onPositionChange={handleAudioPosition}
          onEnded={completeBrowserSegment}
          onError={() => setError("音频暂时无法播放")}
        />
      ) : null}

      <div className="player-topbar">
        <Link href="/" className="icon-button glass-button" aria-label="返回节目"><WaveIcon name="back" /></Link>
        <div className="player-grabber" />
        <details className="player-more-menu">
          <summary className="icon-button glass-button" aria-label="更多"><WaveIcon name="more" /></summary>
          <div className="player-more-popover">
            <button
              type="button"
              onClick={() => void prepareAndSaveEpisode()}
              disabled={saveState !== "idle" || saved}
            >
              {saveState !== "idle"
                ? "正在准备并保存…"
                : saved
                  ? "已保存到节目库"
                  : localEpisode.state === "MATERIALIZED"
                    ? "保存到节目库"
                    : "准备并保存完整节目"}
            </button>
            <button type="button" onClick={() => void exportEpisode()} disabled={localEpisode.state !== "MATERIALIZED" || exportState === "preparing"}>
              {exportState === "preparing" ? "正在准备导出…" : "导出 MP3"}
            </button>
            {localEpisode.is_listener_active
              ? (
                  <button type="button" onClick={leaveEpisode}>
                    {localEpisode.state === "MATERIALIZING"
                      ? "停止播放（完整节目继续准备）"
                      : "停止后台准备"}
                  </button>
                )
              : <button type="button" onClick={resumePlayback}>恢复节目</button>}
          </div>
        </details>
      </div>

      <section className="player-artwork-section">
        <ProgramArtwork
          title={localEpisode.title ?? "WaveCast"}
          subtitle={chapterTitle}
          seed={(localEpisode.seed_id.length * 97) + currentChapterIndex}
          className="player-artwork"
        />
      </section>

      <section className="player-copy">
        <p className="program-kicker">WAVECAST PROGRAM</p>
        <h1>{localEpisode.title ?? "正在播放"}</h1>
        <p className="chapter-line">Chapter {currentChapterIndex + 1} · {chapterTitle}</p>
        <p className="track-line">
          {displayCurrent?.kind === "MUSIC"
            ? [displayCurrent.artist, displayCurrent.title].filter(Boolean).join(" — ")
            : displayCurrent?.title ?? "主持人正在串联"}
        </p>
      </section>

      <section className="player-progress">
        <input
          aria-label="节目进度"
          type="range"
          min="0"
          max={Math.max(1, maxSeekPosition)}
          value={Math.min(displayedPosition, Math.max(1, maxSeekPosition))}
          onChange={(event) => {
            const value = Number(event.target.value);
            if (masterMode) {
              seekPreviewRef.current = value;
              setSeekPreview(value);
              return;
            }
            const linearValue = transportMixPlan
              ? mixPositionToLinearPosition(
                  localEpisode,
                  transportMixPlan,
                  value,
                ).linearPositionSeconds
              : value;
            if (isSeekAllowed(localEpisode, linearValue)) {
              seekPreviewRef.current = value;
              setSeekPreview(value);
            }
          }}
          onPointerUp={commitSeekPreview}
          onKeyUp={commitSeekPreview}
          onBlur={commitSeekPreview}
          style={{ "--generated": generatedPercent + "%" } as React.CSSProperties}
        />
        <div><span>{formatSeconds(displayedPosition)}</span><span>-{formatSeconds(remaining)}</span></div>
      </section>

      <section className="transport-controls" aria-label="播放控制">
        <button type="button" className="transport-secondary" aria-label="后退 15 秒" onClick={() => nudgeSeek(-15)}>
          <WaveIcon name="skipBack" size={27} />
        </button>
        <button
          type="button"
          className="transport-primary"
          aria-label={browserPlaying ? "暂停" : "继续播放"}
          onClick={browserPlaying ? pausePlayback : resumePlayback}
        >
          <WaveIcon name={browserPlaying ? "pause" : "play"} size={30} />
        </button>
        <button type="button" className="transport-secondary" aria-label="前进 30 秒" onClick={() => nudgeSeek(30)}>
          <WaveIcon name="skipForward" size={27} />
        </button>
      </section>

      <section className="player-utilities">
        <button type="button" className="utility-button" onClick={() => setChaptersOpen(true)}>
          <WaveIcon name="list" size={21} />
          <span>节目时间轴</span>
        </button>
        <button type="button" className="utility-button" onClick={() => void nextPlayback()}>
          <WaveIcon name="chevron" size={21} />
          <span>下一章节</span>
        </button>
      </section>

      {masterMode && masterBuffering ? (
        <div className="preparing-hint"><i />正在缓冲节目音频</div>
      ) : masterArtifact && !masterMode ? (
        <div className="preparing-hint"><i />完整节目音频已准备，正在切换单音源播放</div>
      ) : preparingAhead ? (
        <div className="preparing-hint"><i />正在准备接下来的章节</div>
      ) : upcoming ? (
        <div className="up-next">接下来：<strong>{upcoming.title}</strong>{upcoming.artist ? " · " + upcoming.artist : ""}</div>
      ) : null}

      {error ? <p className="player-error">{error}</p> : null}
      {exportError ? <p className="player-error">{exportError}</p> : null}
      {exportArtifact ? <a className="export-download" href={exportArtifact.audioUrl} download={downloadFilename(exportArtifact.episodeId)}>再次下载 MP3</a> : null}

      <ChaptersSheet
        episode={localEpisode}
        open={chaptersOpen}
        onClose={() => setChaptersOpen(false)}
        currentSegmentId={displayCurrent?.id ?? null}
      />
    </main>
  );
}
