"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, ApiRequestError } from "./api";
import { subscribeToEpisodeEvents } from "./episode-events";
import { createSynchronizationGuard } from "./episode-synchronization";
import {
  ExportBlockedError,
  prepareEpisodeExport,
  triggerMixdownDownload,
  type MixdownArtifact,
} from "./episode-export";
import { nextJumpStart, nextVisibleSegment, shouldExtendRender } from "./playback";
import {
  activeMixClipsAt,
  mixPlanSignature,
  type MixPlan,
} from "./mix-timeline";
import { FULL_VERSION_POLL_MS, playerFullVersion, unwatchFullVersion, watchFullVersion } from "./full-versions";
import { usePlayerStore } from "./player-store";
import type {
  LiveEpisode,
  ProgramRenderManifest,
  Segment,
} from "./types";
import {
  isEpisodeSaved,
  recordRecentEpisode,
  saveMaterializedEpisode,
} from "./user-library";

const PROGRAM_CHECKPOINT_SECONDS = 5;
const PROGRAM_PROGRESS_PREFIX = "wavecast-program-progress:";
const PROGRAM_MANIFEST_PREFIX = "wavecast-program-manifest:";

type StoredProgramProgress = {
  positionSeconds: number;
  updatedAtMs: number;
  continueWhileHidden: boolean;
};

function storedProgramProgress(
  episodeId: string,
): StoredProgramProgress | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(PROGRAM_PROGRESS_PREFIX + episodeId);
  if (raw === null) return null;

  // Backward compatibility with the original numeric-only checkpoint.
  const legacy = Number(raw);
  if (Number.isFinite(legacy) && legacy >= 0) {
    return {
      positionSeconds: legacy,
      updatedAtMs: Date.now(),
      continueWhileHidden: false,
    };
  }

  try {
    const stored = JSON.parse(raw) as Partial<StoredProgramProgress>;
    const position = Number(stored.positionSeconds);
    const updatedAtMs = Number(stored.updatedAtMs);
    if (!Number.isFinite(position) || position < 0) return null;
    return {
      positionSeconds: position,
      updatedAtMs: Number.isFinite(updatedAtMs) ? updatedAtMs : Date.now(),
      continueWhileHidden: stored.continueWhileHidden === true,
    };
  } catch {
    return null;
  }
}

function resolvedProgramPosition(stored: StoredProgramProgress | null): number | null {
  if (!stored) return null;
  if (!stored.continueWhileHidden) return stored.positionSeconds;
  const elapsed = Math.max(0, (Date.now() - stored.updatedAtMs) / 1000);
  return stored.positionSeconds + elapsed;
}

function storedProgramPosition(episodeId: string): number | null {
  return resolvedProgramPosition(storedProgramProgress(episodeId));
}

function storeProgramPosition(
  episodeId: string,
  position: number,
  continueWhileHidden = false,
): void {
  if (typeof window === "undefined") return;
  const value: StoredProgramProgress = {
    positionSeconds: Math.max(0, position),
    updatedAtMs: Date.now(),
    continueWhileHidden,
  };
  window.localStorage.setItem(
    PROGRAM_PROGRESS_PREFIX + episodeId,
    JSON.stringify(value),
  );
}

function storedProgramManifest(
  episodeId: string | null,
): ProgramRenderManifest | null {
  if (typeof window === "undefined" || !episodeId) return null;
  const raw = window.sessionStorage.getItem(PROGRAM_MANIFEST_PREFIX + episodeId);
  if (!raw) return null;
  try {
    const manifest = JSON.parse(raw) as ProgramRenderManifest;
    if (
      manifest?.schemaVersion !== 1
      || manifest.episodeId !== episodeId
      || !manifest.streamUrl
      || !Array.isArray(manifest.chunks)
      || manifest.chunks.length === 0
      || !(manifest.renderedFrontierSeconds > 0)
    ) {
      return null;
    }
    return manifest;
  } catch {
    return null;
  }
}

function storeProgramManifest(manifest: ProgramRenderManifest): void {
  if (typeof window === "undefined") return;
  window.sessionStorage.setItem(
    PROGRAM_MANIFEST_PREFIX + manifest.episodeId,
    JSON.stringify(manifest),
  );
}

function renderSignature(episode: LiveEpisode): string {
  return JSON.stringify({
    id: episode.id,
    state: episode.state,
    host: episode.presentation_intent?.host_mode ?? "LIGHT",
    segments: episode.segments.map((segment) => [
      segment.id,
      segment.order,
      segment.state,
      segment.audio_source_url,
      segment.actual_duration_seconds,
      segment.planned_duration_seconds,
    ]),
  });
}

function segmentAtProgramPosition(
  episode: LiveEpisode,
  plan: MixPlan | null,
  positionSeconds: number,
): Segment | undefined {
  if (plan) {
    const active = activeMixClipsAt(plan, positionSeconds);
    const preferred = (
      active.find((clip) => clip.lane === "VOICE")
      ?? [...active].reverse().find((clip) => clip.lane === "MUSIC")
      ?? [...plan.clips]
        .filter((clip) => clip.timelineStartSeconds <= positionSeconds)
        .sort((left, right) => right.timelineStartSeconds - left.timelineStartSeconds)[0]
    );
    if (preferred) {
      const segment = episode.segments.find(
        (candidate) => candidate.id === preferred.segmentId,
      );
      if (segment) return segment;
    }
  }
  return episode.segments.find(
    (segment) => segment.id === episode.current_segment_id,
  ) ?? episode.segments.find((segment) => segment.state !== "SKIPPED");
}

export type ProgrammePlaybackTarget = {
  seedId?: string;
  episodeId?: string;
};

/**
 * Programme playback runtime extracted verbatim from EpisodePlayer: HLS render
 * requests with bounded retry, heartbeat, progress persistence, export,
 * materialization and background-preparation control. UI components consume
 * this hook and must not reimplement any of these behaviours.
 */
export function useProgrammePlayback({
  seedId,
  episodeId,
  leaveIfAbandoned = false,
}: ProgrammePlaybackTarget & {
  /**
   * When a new episode's start resolves after this host was unmounted
   * (cancelled or replaced), release it so the server stops generating.
   */
  leaveIfAbandoned?: boolean;
}) {
  const { episode, setEpisode } = usePlayerStore();
  const bootstrapEpisodeId = (
    episodeId
    ?? (
      episode
      && (!seedId || episode.seed_id === seedId)
        ? episode.id
        : null
    )
  );
  const bootstrapPosition = bootstrapEpisodeId
    ? storedProgramPosition(bootstrapEpisodeId) ?? 0
    : 0;
  const bootstrapManifest = storedProgramManifest(bootstrapEpisodeId);
  const bootstrapPlaying = Boolean(
    episode
    && episode.id === bootstrapEpisodeId
    && episode.is_listener_active,
  );

  const [error, setError] = useState<string | null>(null);
  const [browserPosition, setBrowserPosition] = useState(bootstrapPosition);
  const [browserPlaying, setBrowserPlaying] = useState(bootstrapPlaying);
  const [mixPlan, setMixPlan] = useState<MixPlan | null>(null);
  const [programManifest, setProgramManifest] =
    useState<ProgramRenderManifest | null>(bootstrapManifest);
  const [renderState, setRenderState] =
    useState<"idle" | "preparing" | "ready" | "error">(
      bootstrapManifest ? "ready" : "idle",
    );
  const [renderStatusChecked, setRenderStatusChecked] = useState(false);
  const [programBuffering, setProgramBuffering] = useState(false);
  const [renderRetryNonce, setRenderRetryNonce] = useState(0);
  const [seekToken, setSeekToken] = useState(0);
  const [seekPreview, setSeekPreview] = useState<number | null>(null);
  const [exportState, setExportState] =
    useState<"idle" | "preparing" | "ready" | "error">("idle");
  const [exportArtifact, setExportArtifact] =
    useState<MixdownArtifact | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [saveState, setSaveState] =
    useState<"idle" | "requesting" | "preparing">("idle");

  const episodeIdRef = useRef<string | null>(bootstrapEpisodeId);
  const browserPositionRef = useRef(bootstrapPosition);
  const browserPlayingRef = useRef(bootstrapPlaying);
  const recoveringSessionRef = useRef(false);
  const sessionRecoveryAttemptsRef = useRef(0);
  const seekPreviewRef = useRef<number | null>(null);
  const checkpointBucketRef = useRef(-1);
  const materializationRequestVersionRef = useRef<number | null>(null);
  const localEpisodeRef = useRef<LiveEpisode | null>(null);
  const synchronizationGuardRef = useRef(createSynchronizationGuard());
  const renderInFlightRef = useRef(false);
  const renderQueuedRef = useRef(false);
  const renderSignatureRef = useRef<string | null>(null);
  const renderedSignatureRef = useRef<string | null>(null);
  const renderRetryTimerRef = useRef<number | null>(null);
  const renderRetryStateRef = useRef<{ signature: string | null; count: number }>({
    signature: null,
    count: 0,
  });
  const programManifestRef = useRef<ProgramRenderManifest | null>(bootstrapManifest);
  const frontierWakeAtRef = useRef(0);
  programManifestRef.current = programManifest;

  const localEpisode = episode
    && (episodeId ? episode.id === episodeId : episode.seed_id === seedId)
    ? episode
    : null;
  localEpisodeRef.current = localEpisode;

  const arrangementSignature = useMemo(
    () => localEpisode ? mixPlanSignature(localEpisode) : null,
    [localEpisode],
  );
  const currentRenderSignature = useMemo(
    () => localEpisode ? renderSignature(localEpisode) : null,
    [localEpisode],
  );
  renderSignatureRef.current = currentRenderSignature;

  const current = useMemo(
    () => localEpisode
      ? segmentAtProgramPosition(localEpisode, mixPlan, browserPosition)
      : undefined,
    [browserPosition, localEpisode, mixPlan],
  );
  const upcoming = useMemo(
    () => localEpisode && current
      ? nextVisibleSegment(localEpisode, current.id)
      : undefined,
    [current, localEpisode],
  );

  const requestProgramRender = useCallback(() => {
    if (renderInFlightRef.current) {
      renderQueuedRef.current = true;
      return;
    }
    const targetEpisode = localEpisodeRef.current;
    if (!targetEpisode) return;

    renderInFlightRef.current = true;
    setRenderState((state) => state === "ready" ? state : "preparing");
    const episodeIdAtRequest = targetEpisode.id;
    const signatureAtRequest = renderSignatureRef.current;

    void api.programRender(episodeIdAtRequest)
      .then((manifest) => {
        if (localEpisodeRef.current?.id !== episodeIdAtRequest) return;
        storeProgramManifest(manifest);
        setProgramManifest(manifest);
        renderedSignatureRef.current = signatureAtRequest;
        renderRetryStateRef.current = { signature: signatureAtRequest, count: 0 };
        if (renderRetryTimerRef.current !== null) {
          window.clearTimeout(renderRetryTimerRef.current);
          renderRetryTimerRef.current = null;
        }
        setRenderRetryNonce(0);
        setRenderState("ready");
        setError(null);
      })
      .catch((reason: unknown) => {
        if (localEpisodeRef.current?.id !== episodeIdAtRequest) return;
        if (
          reason instanceof ApiRequestError
          && [409, 502, 503].includes(reason.status)
        ) {
          // Progressive generation can briefly expose a render plan before all
          // source/renderer inputs have settled. Keep an already-published
          // immutable prefix, or stay in the preparing state when this is the
          // first render, and retry with bounded backoff. A genuine persistent
          // renderer failure will still surface after the retry budget expires.
          const retry = renderRetryStateRef.current;
          if (retry.signature !== signatureAtRequest) {
            retry.signature = signatureAtRequest;
            retry.count = 0;
          }
          const maxRetries = reason.status === 409 ? 6 : 6;
          if (retry.count < maxRetries && renderRetryTimerRef.current === null) {
            setRenderState((state) => state === "ready" ? state : "preparing");
            setError(null);
            retry.count += 1;
            const delayMs = reason.status === 409
              ? retry.count * 1_000
              : retry.count * 1_500;
            renderRetryTimerRef.current = window.setTimeout(() => {
              renderRetryTimerRef.current = null;
              setRenderRetryNonce((value) => value + 1);
            }, delayMs);
            return;
          }
        }
        if (
          reason instanceof ApiRequestError
          && [409, 502, 503].includes(reason.status)
          && programManifestRef.current
        ) {
          // The published programme prefix remains authoritative. A failed
          // background extension must never replace working playback with an
          // internal renderer error; frontier wake/polling may try again later.
          setRenderState("ready");
          setError(null);
          return;
        }
        setRenderState("error");
        setError(
          reason instanceof ApiRequestError
            ? "节目音频暂时没有准备好"
            : reason instanceof Error
              ? reason.message
              : "节目音频暂时没有准备好",
        );
      })
      .finally(() => {
        renderInFlightRef.current = false;
        if (renderQueuedRef.current) {
          renderQueuedRef.current = false;
          queueMicrotask(requestProgramRender);
        }
      });
  }, []);

  useEffect(() => {
    const cachedManifest = storedProgramManifest(localEpisode?.id ?? null);
    setProgramManifest(cachedManifest);
    setRenderState(cachedManifest ? "ready" : "idle");
    setProgramBuffering(false);
    setRenderRetryNonce(0);
    setRenderStatusChecked(false);
    renderedSignatureRef.current = null;
    renderQueuedRef.current = false;
    checkpointBucketRef.current = -1;
    frontierWakeAtRef.current = 0;
    renderRetryStateRef.current = { signature: null, count: 0 };
    if (renderRetryTimerRef.current !== null) {
      window.clearTimeout(renderRetryTimerRef.current);
      renderRetryTimerRef.current = null;
    }
    return () => {
      if (renderRetryTimerRef.current !== null) {
        window.clearTimeout(renderRetryTimerRef.current);
        renderRetryTimerRef.current = null;
      }
    };
  }, [localEpisode?.id]);

  useEffect(() => {
    if (!localEpisode?.id) return;
    let cancelled = false;
    const episodeIdAtLookup = localEpisode.id;

    // Re-entering the player should reuse the already-published immutable
    // manifest immediately. A POST render can still extend it in the
    // background, but must not gate the UI on an expensive full-prefix render.
    setRenderState((state) => state === "ready" ? state : "preparing");
    void api.programRenderStatus(episodeIdAtLookup)
      .then((manifest) => {
        if (cancelled || localEpisodeRef.current?.id !== episodeIdAtLookup) return;
        storeProgramManifest(manifest);
        setProgramManifest(manifest);
        setRenderState("ready");
        setError(null);
      })
      .catch((reason: unknown) => {
        if (cancelled || localEpisodeRef.current?.id !== episodeIdAtLookup) return;
        if (!(reason instanceof ApiRequestError && reason.status === 404)) {
          // Status lookup is only an optimization. The normal POST render path
          // below remains the source of truth if the lookup is unavailable.
          setRenderState((state) => state === "ready" ? state : "preparing");
        }
      })
      .finally(() => {
        if (!cancelled && localEpisodeRef.current?.id === episodeIdAtLookup) {
          setRenderStatusChecked(true);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [localEpisode?.id]);

  useEffect(() => {
    if (!localEpisode?.id || !arrangementSignature) {
      setMixPlan(null);
      return;
    }
    let cancelled = false;
    void api.mixPlan(localEpisode.id)
      .then((plan) => {
        if (!cancelled) setMixPlan(plan);
      })
      .catch(() => {
        // The programme stream remains authoritative. MixPlan is used here only
        // to label the current rendered position in the UI.
      });
    return () => {
      cancelled = true;
    };
  }, [arrangementSignature, localEpisode?.id]);

  useEffect(() => {
    if (
      renderStatusChecked
      && currentRenderSignature
      && (
        currentRenderSignature !== renderedSignatureRef.current
        || renderRetryNonce > 0
      )
    ) {
      requestProgramRender();
    }
  }, [
    currentRenderSignature,
    renderRetryNonce,
    renderStatusChecked,
    requestProgramRender,
  ]);

  useEffect(() => {
    // An idle host (nothing selected yet) loads nothing.
    if (!episodeId && !seedId) return;
    let mounted = true;

    const load = episodeId ? api.get(episodeId) : api.start(seedId!);
    load.then((started) => {
      episodeIdRef.current = started.id;
      void api.recordUserEvent({
        event_type: "PLAY_START",
        program_id: started.seed_id,
        episode_id: started.id,
      }).catch(() => undefined);
      if (!mounted) {
        if (leaveIfAbandoned && !episodeId) {
          void api.leave(started.id).catch(() => undefined);
        }
        return;
      }

      const storedProgress = storedProgramProgress(started.id);
      const stored = resolvedProgramPosition(storedProgress);
      // Only listener-owned playback state may restore <audio>.currentTime.
      // program_playback_position_seconds is generation scheduling metadata and
      // must never become transport authority.
      const initialPosition = stored ?? 0;
      const shouldResume = storedProgress?.continueWhileHidden === true;
      setEpisode(started);
      setBrowserPlaying(shouldResume || started.is_listener_active);
      browserPlayingRef.current = shouldResume || started.is_listener_active;
      setBrowserPosition(initialPosition);
      browserPositionRef.current = initialPosition;
      setSeekToken((token) => token + 1);

      // iOS may suspend long enough for the server-side listener lease to
      // expire. If the listener was actively playing when the page went
      // background, restore that lease automatically on remount.
      if (shouldResume && !started.is_listener_active) {
        void api.resume(started.id)
          .then((resumed) => {
            if (!mounted) return;
            setEpisode(resumed);
            setBrowserPlaying(true);
            browserPlayingRef.current = true;
            setError(null);
          })
          .catch(() => {
            // Keep the local resume intent; an explicit tap can retry if the
            // browser's autoplay policy requires user interaction.
          });
      }
    }).catch((reason: unknown) => {
      if (!mounted) return;
      setError(
        reason instanceof Error ? reason.message : "节目暂时无法开始",
      );
    });

    return () => {
      // Route changes, Safari background suspension and component remounts are
      // not listener intent. Only the explicit "停止后台准备" action may call
      // /leave; otherwise MINI-player re-entry must resume the same session.
      mounted = false;
    };
  }, [episodeId, leaveIfAbandoned, seedId, setEpisode]);

  useEffect(() => {
    if (!localEpisode) return;
    return subscribeToEpisodeEvents(localEpisode.id, setEpisode);
  }, [localEpisode?.id, setEpisode]);

  // The event stream can be cut by a proxy; while a 完整版 is being asked for, look at the episode too.
  useEffect(() => {
    if (saveState !== "preparing" || !localEpisode?.id) return;
    const id = localEpisode.id;
    const timer = window.setInterval(() => {
      void api.get(id).then(setEpisode).catch(() => undefined);
    }, FULL_VERSION_POLL_MS);
    return () => window.clearInterval(timer);
  }, [localEpisode?.id, saveState, setEpisode]);

  useEffect(() => {
    setExportState("idle");
    setExportArtifact(null);
    setExportError(null);
  }, [localEpisode?.id]);

  useEffect(() => {
    if (!localEpisode?.id) return;

    const persistForLifecycle = () => {
      const continuing = (
        document.visibilityState === "hidden"
        && browserPlayingRef.current
      );
      storeProgramPosition(
        localEpisode.id,
        browserPositionRef.current,
        continuing,
      );
    };

    document.addEventListener("visibilitychange", persistForLifecycle);
    window.addEventListener("pagehide", persistForLifecycle);

    return () => {
      document.removeEventListener("visibilitychange", persistForLifecycle);
      window.removeEventListener("pagehide", persistForLifecycle);
      // visibilitychange/pagehide already captured the original hidden
      // timestamp. Rewriting the same stale position during an iOS background
      // teardown would erase the elapsed background time.
      if (document.visibilityState !== "hidden") {
        storeProgramPosition(
          localEpisode.id,
          browserPositionRef.current,
          false,
        );
      }
    };
  }, [localEpisode?.id]);

  useEffect(() => {
    if (!localEpisode) return;
    recordRecentEpisode(
      localEpisode,
      current?.title ?? null,
      browserPositionRef.current,
    );
    setSaved(isEpisodeSaved(localEpisode.id));
  }, [current?.id, current?.title, localEpisode?.id]);

  // The server drops the listener lease after 30s without a heartbeat (a
  // throttled background tab, a flaky mobile network). While the listener still
  // intends to play, take the lease back instead of leaving generation stopped
  // behind a player that silently runs out of programme.
  const recoverListenerSession = useCallback(() => {
    const target = localEpisodeRef.current;
    if (!target || !browserPlayingRef.current) return;
    if (target.state === "MATERIALIZED" || target.state === "PUBLISHED") return;
    if (recoveringSessionRef.current) return;
    recoveringSessionRef.current = true;
    void api.resume(target.id)
      .then((resumed) => {
        if (localEpisodeRef.current?.id !== resumed.id) return;
        setEpisode(resumed);
        setError(null);
      })
      .catch(() => {
        // The next heartbeat or lease check tries again.
      })
      .finally(() => {
        recoveringSessionRef.current = false;
      });
  }, [setEpisode]);

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
      } catch (reason: unknown) {
        // 409: the server already expired this lease; heartbeats alone cannot
        // revive it ("resume it before generating").
        if (reason instanceof ApiRequestError && reason.status === 409) {
          recoverListenerSession();
        }
        // Otherwise heartbeat only owns listener liveness and scheduling.
      }
    };
    void heartbeat();
    const interval = window.setInterval(() => void heartbeat(), 10_000);
    return () => {
      synchronizationGuard.invalidate();
      window.clearInterval(interval);
    };
  }, [localEpisode?.id, localEpisode?.is_listener_active, recoverListenerSession]);

  // The episode itself reports the lease as gone (event stream or reload) while
  // the listener is still playing: resume, a few times at most per spell.
  useEffect(() => {
    if (!localEpisode) return;
    if (localEpisode.is_listener_active) {
      sessionRecoveryAttemptsRef.current = 0;
      return;
    }
    if (!browserPlaying) return;
    const tryResume = () => {
      if (sessionRecoveryAttemptsRef.current >= 3) return;
      sessionRecoveryAttemptsRef.current += 1;
      recoverListenerSession();
    };
    tryResume();
    const interval = window.setInterval(tryResume, 4_000);
    return () => window.clearInterval(interval);
  }, [browserPlaying, localEpisode?.id, localEpisode?.is_listener_active, recoverListenerSession]);

  const leaveEpisode = useCallback(() => {
    const target = localEpisodeRef.current;
    if (!target) return;
    setBrowserPlaying(false);
    synchronizationGuardRef.current.invalidate();
    void api.programCheckpoint(target.id, browserPositionRef.current)
      .catch(() => undefined);
    void api.leave(target.id)
      .then(setEpisode)
      .catch((reason: unknown) => {
        setError(
          reason instanceof Error ? reason.message : "停止后台准备失败",
        );
      });
  }, [setEpisode]);

  const exportEpisode = useCallback(async () => {
    if (
      !localEpisode
      || localEpisode.state !== "MATERIALIZED"
      || exportState === "preparing"
    ) return;
    setExportState("preparing");
    setExportError(null);
    try {
      const artifact = await prepareEpisodeExport(
        localEpisode.id,
        {
          prepareMixdown: api.prepareMixdown,
          mixdown: api.mixdown,
        },
        exportArtifact,
      );
      setExportArtifact(artifact);
      setExportState("ready");
      triggerMixdownDownload(artifact, localEpisode.id);
    } catch (reason: unknown) {
      setExportState("error");
      setExportError(
        reason instanceof ExportBlockedError
          ? "部分音源暂时无法准备导出，请稍后重试。"
          : reason instanceof Error
            ? reason.message
            : "导出失败，请稍后重试。",
      );
    }
  }, [exportArtifact, exportState, localEpisode]);

  const persistMaterializedEpisode = useCallback((ready: LiveEpisode) => {
    const listenerPosition = browserPositionRef.current;
    recordRecentEpisode(ready, current?.title ?? null, listenerPosition);
    if (!saveMaterializedEpisode(
      ready,
      current?.title ?? null,
      listenerPosition,
    )) {
      throw new Error("完整版还没有准备好");
    }
    setSaved(true);
    unwatchFullVersion(ready.id);
    setError(null);
    void api.recordUserEvent({
      event_type: "SAVE",
      program_id: ready.seed_id,
      episode_id: ready.id,
    }).catch(() => undefined);
  }, [current?.title]);

  /** Asks for the 完整版 (the whole episode, prepared in the background); "limit" = too many at once. */
  const prepareFullVersion = useCallback(async (): Promise<"started" | "ready" | "limit" | "failed"> => {
    if (!localEpisode || saveState !== "idle" || saved) return "failed";
    if (localEpisode.state === "MATERIALIZED") {
      try {
        persistMaterializedEpisode(localEpisode);
        return "ready";
      } catch (reason: unknown) {
        setError(
          reason instanceof Error
            ? reason.message
            : "完整版没有准备成功，请稍后重试",
        );
        return "failed";
      }
    }

    setSaveState("requesting");
    try {
      const requested = await api.materialize(localEpisode.id);
      materializationRequestVersionRef.current = requested.version;
      setEpisode(requested);
      if (requested.state === "MATERIALIZED") {
        persistMaterializedEpisode(requested);
        setSaveState("idle");
        return "ready";
      }
      watchFullVersion({
        episodeId: requested.id,
        programmeId: requested.seed_id,
        title: requested.title ?? "WaveCast 节目",
      });
      setSaveState("preparing");
      return "started";
    } catch (reason: unknown) {
      materializationRequestVersionRef.current = null;
      setSaveState("idle");
      if (reason instanceof ApiRequestError && reason.status === 429) return "limit";
      setError(
        reason instanceof Error
          ? reason.message
          : "完整版没有准备成功，请稍后重试",
      );
      return "failed";
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
        requestProgramRender();
      } catch (reason: unknown) {
        setError(
          reason instanceof Error ? reason.message : "完整版没有准备成功，请稍后重试",
        );
      } finally {
        materializationRequestVersionRef.current = null;
        setSaveState("idle");
      }
      return;
    }
    if (localEpisode.state === "MATERIALIZING") return;

    const requestedVersion = materializationRequestVersionRef.current;
    if (
      requestedVersion !== null
      && localEpisode.version > requestedVersion
    ) {
      materializationRequestVersionRef.current = null;
      setSaveState("idle");
      setError("完整版没有准备成功，可以稍后重试");
    }
  }, [
    localEpisode,
    persistMaterializedEpisode,
    requestProgramRender,
    saveState,
  ]);

  const handleProgramPosition = useCallback((position: number) => {
    const target = localEpisodeRef.current;
    if (!target || seekPreviewRef.current !== null) return;
    const nextPosition = Math.max(0, position);
    setBrowserPosition(nextPosition);
    browserPositionRef.current = nextPosition;
    storeProgramPosition(
      target.id,
      nextPosition,
      document.visibilityState === "hidden" && browserPlayingRef.current,
    );

    const bucket = Math.floor(nextPosition / PROGRAM_CHECKPOINT_SECONDS);
    if (bucket !== checkpointBucketRef.current) {
      checkpointBucketRef.current = bucket;
      void api.programCheckpoint(target.id, nextPosition)
        .catch(() => undefined);
    }
  }, []);

  const commitSeek = useCallback((value: number) => {
    const manifest = programManifest;
    if (!manifest) return;
    const max = Math.max(0, manifest.renderedFrontierSeconds);
    const target = Math.max(0, Math.min(value, max));
    setBrowserPosition(target);
    browserPositionRef.current = target;
    seekPreviewRef.current = null;
    setSeekPreview(null);
    setSeekToken((token) => token + 1);
    const targetEpisode = localEpisodeRef.current;
    if (targetEpisode) {
      storeProgramPosition(targetEpisode.id, target);
      void api.programCheckpoint(targetEpisode.id, target)
        .catch(() => undefined);
    }
  }, [programManifest]);

  const commitSeekPreview = useCallback(() => {
    const preview = seekPreviewRef.current;
    if (preview === null) return;
    seekPreviewRef.current = null;
    setSeekPreview(null);
    commitSeek(preview);
  }, [commitSeek]);

  const pausePlayback = useCallback(() => {
    setBrowserPlaying(false);
    browserPlayingRef.current = false;
    const target = localEpisodeRef.current;
    if (target) {
      storeProgramPosition(target.id, browserPositionRef.current, false);
      void api.programCheckpoint(target.id, browserPositionRef.current)
        .catch(() => undefined);
    }
  }, []);

  const resumePlayback = useCallback(() => {
    const target = localEpisodeRef.current;
    if (!target) return;
    setBrowserPlaying(true);
    browserPlayingRef.current = true;
    storeProgramPosition(
      target.id,
      browserPositionRef.current,
      document.visibilityState === "hidden",
    );
    if (target.is_listener_active) return;
    void api.resume(target.id)
      .then((resumed) => {
        setEpisode(resumed);
        setError(null);
      })
      .catch((reason: unknown) => {
        setBrowserPlaying(false);
        setError(
          reason instanceof Error
            ? reason.message
            : "节目暂时无法恢复",
        );
      });
  }, [setEpisode]);

  const handleProgrammeEnded = useCallback(() => {
    const target = localEpisodeRef.current;
    setBrowserPlaying(false);
    browserPlayingRef.current = false;
    if (!target) return;
    void api.programCheckpoint(target.id, browserPositionRef.current)
      .catch(() => undefined);
    void api.recordUserEvent({
      event_type: "PLAY_COMPLETE",
      program_id: target.seed_id,
      episode_id: target.id,
    }).catch(() => undefined);
  }, []);

  const handleFrontierReached = useCallback(() => {
    const now = Date.now();
    if (now - frontierWakeAtRef.current < 5_000) return;
    frontierWakeAtRef.current = now;

    const target = localEpisodeRef.current;
    if (target) {
      // This cursor is scheduling metadata only. The endpoint queues generation
      // without advancing lifecycle segments or rewriting programme content.
      void api.programCheckpoint(target.id, browserPositionRef.current)
        .catch(() => undefined);
    }
    // Re-rendering the same structural signature is safe: the renderer verifies
    // the frozen prefix byte-for-byte and can append newly available HLS chunks.
    requestProgramRender();
  }, [requestProgramRender]);

  // A finished programme is rendered a few minutes at a time: keep asking for more ahead of the listener.
  const extendTick = Math.floor(browserPosition / 10);
  useEffect(() => {
    if (shouldExtendRender({
      episodeState: localEpisode?.state ?? null,
      manifest: programManifest,
      positionSeconds: browserPositionRef.current,
    })) requestProgramRender();
  }, [extendTick, localEpisode?.state, programManifest, requestProgramRender]);

  const maxSeekPosition = programManifest?.renderedFrontierSeconds ?? 0;
  const displayedPosition = Math.min(
    seekPreview ?? browserPosition,
    maxSeekPosition,
  );
  const preparingAhead = Boolean(
    programManifest
    && !programManifest.complete
    && maxSeekPosition - browserPosition < 45,
  );

  const updateSeekPreview = useCallback((value: number) => {
    seekPreviewRef.current = value;
    setSeekPreview(value);
  }, []);

  const nudgeSeek = useCallback((seconds: number) => {
    commitSeek(browserPositionRef.current + seconds);
  }, [commitSeek]);

  const nextPlayback = useCallback(() => {
    const target = localEpisodeRef.current;
    if (!target) return;
    if (!mixPlan) {
      setError("后面的内容还没有准备好");
      return;
    }
    const position = browserPositionRef.current;
    const nextStart = nextJumpStart(mixPlan, position, target);
    if (nextStart === undefined || nextStart >= maxSeekPosition) {
      setError("后面的内容还在准备中");
      return;
    }
    // Leaving host speech is not a verdict on a song: only skipping over playing music is a signal.
    const musicPlaying = activeMixClipsAt(mixPlan, position).some((clip) => clip.lane === "MUSIC");
    commitSeek(nextStart);
    if (!musicPlaying) return;
    void api.recordUserEvent({
      event_type: "SKIP",
      program_id: target.seed_id,
      episode_id: target.id,
    }).catch(() => undefined);
  }, [commitSeek, maxSeekPosition, mixPlan]);

  const mediaTitle = current?.kind === "MUSIC"
    ? current.title
    : localEpisode?.title ?? "WaveCast";
  const mediaArtist = current?.kind === "MUSIC"
    ? current.artist
    : "WaveCast";

  const handlePlayingChange = useCallback((playing: boolean) => {
    if (playing) {
      setProgramBuffering(false);
      setBrowserPlaying(true);
      browserPlayingRef.current = true;
    }
  }, []);

  const fullVersion = playerFullVersion(localEpisode, saved, saveState !== "idle");

  return {
    localEpisode,
    error,
    setError,
    mixPlan,
    programManifest,
    renderState,
    programBuffering,
    setProgramBuffering,
    browserPosition,
    browserPlaying,
    seekToken,
    seekPreview,
    current,
    upcoming,
    maxSeekPosition,
    displayedPosition,
    preparingAhead,
    mediaTitle: mediaTitle || localEpisode?.title || "WaveCast",
    mediaArtist,
    exportState,
    exportArtifact,
    exportError,
    saved,
    saveState,
    requestProgramRender,
    leaveEpisode,
    exportEpisode,
    prepareFullVersion,
    fullVersion,
    handleProgramPosition,
    handlePlayingChange,
    commitSeek,
    updateSeekPreview,
    commitSeekPreview,
    pausePlayback,
    resumePlayback,
    handleProgrammeEnded,
    handleFrontierReached,
    nudgeSeek,
    nextPlayback,
  };
}

export type ProgrammePlayback = ReturnType<typeof useProgrammePlayback>;
