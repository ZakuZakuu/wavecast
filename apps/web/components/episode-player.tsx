"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, ApiRequestError } from "../lib/api";
import { subscribeToEpisodeEvents } from "../lib/episode-events";
import {
  createSynchronizationGuard,
} from "../lib/episode-synchronization";
import {
  downloadFilename,
  ExportBlockedError,
  prepareEpisodeExport,
  triggerMixdownDownload,
  type MixdownArtifact,
} from "../lib/episode-export";
import { formatSeconds, nextVisibleSegment } from "../lib/playback";
import {
  activeMixClipsAt,
  mixPlanSignature,
  type MixPlan,
} from "../lib/mix-timeline";
import { usePlayerStore } from "../lib/player-store";
import type {
  LiveEpisode,
  ProgramRenderManifest,
  Segment,
} from "../lib/types";
import {
  isEpisodeSaved,
  recordRecentEpisode,
  saveMaterializedEpisode,
} from "../lib/user-library";
import { ChaptersSheet } from "./chapters-sheet";
import { ProgrammeAudioPlayer } from "./programme-audio-player";
import { ProgramArtwork } from "./program-artwork";
import { WaveIcon } from "./wave-icon";

const CHAPTER_TITLES = [
  "开场",
  "夜色开始变暖",
  "从旋律走进城市",
  "另一面的节奏",
  "慢慢收回来",
];
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

export function EpisodePlayer({
  seedId,
  episodeId,
}: {
  seedId?: string;
  episodeId?: string;
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
  const [chaptersOpen, setChaptersOpen] = useState(false);
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
  const frontierWakeAtRef = useRef(0);

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
        setRenderState("error");
        setError(
          reason instanceof Error
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
    let mounted = true;

    const load = episodeId ? api.get(episodeId) : api.start(seedId!);
    load.then((started) => {
      episodeIdRef.current = started.id;
      void api.recordUserEvent({
        event_type: "PLAY_START",
        program_id: started.seed_id,
        episode_id: started.id,
      }).catch(() => undefined);
      if (!mounted) return;

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
  }, [episodeId, seedId, setEpisode]);

  useEffect(() => {
    if (!localEpisode) return;
    return subscribeToEpisodeEvents(localEpisode.id, setEpisode);
  }, [localEpisode?.id, setEpisode]);

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
        // Heartbeat only owns listener liveness and generation scheduling.
      }
    };
    void heartbeat();
    const interval = window.setInterval(() => void heartbeat(), 10_000);
    return () => {
      synchronizationGuard.invalidate();
      window.clearInterval(interval);
    };
  }, [localEpisode?.id, localEpisode?.is_listener_active]);

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
        setError(
          reason instanceof Error
            ? reason.message
            : "保存节目失败，请稍后重试",
        );
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
      setError(
        reason instanceof Error
          ? reason.message
          : "完整节目生成请求失败，请稍后重试",
      );
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
          reason instanceof Error ? reason.message : "保存节目失败，请稍后重试",
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
      setError("完整节目生成失败，可以稍后重试");
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

  if (error && !localEpisode) {
    return (
      <main className="player-state">
        <Link href="/" className="round-back">
          <WaveIcon name="back" />
        </Link>
        <p>{error}</p>
      </main>
    );
  }

  if (!localEpisode) {
    return (
      <main className="player-state">
        <div className="tuning-orb"><i /><i /><i /></div>
        <h1>正在接入节目…</h1>
        <p>节目会先生成一段稳定的单一音频流。</p>
      </main>
    );
  }

  if (
    !programManifest
    || programManifest.chunks.length === 0
    || programManifest.renderedFrontierSeconds <= 0
  ) {
    return (
      <main className="player-state">
        <Link href="/" className="round-back">
          <WaveIcon name="back" />
        </Link>
        <div className="tuning-orb"><i /><i /><i /></div>
        <h1>正在准备节目音频…</h1>
        <p>
          {renderState === "error"
            ? "节目渲染暂时遇到问题，可以稍后重试。"
            : "正在把音乐、主持和转场渲染成一条稳定的节目流。"}
        </p>
        {error ? <p className="player-error">{error}</p> : null}
        <button type="button" onClick={requestProgramRender}>
          重试准备
        </button>
      </main>
    );
  }

  const maxSeekPosition = programManifest.renderedFrontierSeconds;
  const displayedPosition = Math.min(
    seekPreview ?? browserPosition,
    maxSeekPosition,
  );
  // Playback UI uses one programme-time authority. The slider's max, visual
  // fill and remaining-time label must all describe the same currently
  // rendered timeline; generation progress is a separate concern.
  const playedPercent = Math.min(
    100,
    Math.max(
      0,
      (displayedPosition / Math.max(1, maxSeekPosition)) * 100,
    ),
  );
  const remaining = Math.max(0, maxSeekPosition - displayedPosition);
  const chapterIds = Array.from(
    new Set(localEpisode.segments.map((segment) => segment.chapter_id)),
  );
  const currentChapterIndex = Math.max(
    0,
    chapterIds.indexOf(current?.chapter_id ?? chapterIds[0]),
  );
  const chapterTitle = CHAPTER_TITLES[currentChapterIndex]
    ?? "Chapter " + (currentChapterIndex + 1);
  const preparingAhead = (
    !programManifest.complete
    && maxSeekPosition - browserPosition < 45
  );

  const nudgeSeek = (seconds: number) => {
    commitSeek(browserPositionRef.current + seconds);
  };

  const nextPlayback = () => {
    if (!mixPlan || currentChapterIndex + 1 >= chapterIds.length) {
      setError("下一章节还没有准备好");
      return;
    }
    const nextChapterId = chapterIds[currentChapterIndex + 1];
    const starts = localEpisode.segments
      .filter((segment) => (
        segment.chapter_id === nextChapterId
        && segment.state !== "SKIPPED"
      ))
      .map((segment) => mixPlan.segmentStarts[segment.id])
      .filter((value): value is number => typeof value === "number")
      .sort((left, right) => left - right);
    const target = starts[0];
    if (target === undefined || target > maxSeekPosition) {
      setError("下一章节还在准备中");
      return;
    }
    commitSeek(target);
    void api.recordUserEvent({
      event_type: "SKIP",
      program_id: localEpisode.seed_id,
      episode_id: localEpisode.id,
    }).catch(() => undefined);
  };

  const mediaTitle = current?.kind === "MUSIC"
    ? current.title
    : localEpisode.title ?? "WaveCast";
  const mediaArtist = current?.kind === "MUSIC"
    ? current.artist
    : "WaveCast";

  return (
    <main className="now-playing-page page-enter">
      <ProgrammeAudioPlayer
        streamUrl={programManifest.streamUrl}
        playing={browserPlaying && localEpisode.is_listener_active}
        positionSeconds={browserPosition}
        seekToken={seekToken}
        renderedFrontierSeconds={maxSeekPosition}
        complete={programManifest.complete}
        title={mediaTitle || localEpisode.title || "WaveCast"}
        artist={mediaArtist}
        onPositionChange={handleProgramPosition}
        onPlayingChange={(playing) => {
          if (playing) {
            setProgramBuffering(false);
            setBrowserPlaying(true);
            browserPlayingRef.current = true;
          }
        }}
        onBufferingChange={setProgramBuffering}
        onEnded={handleProgrammeEnded}
        onFrontierReached={handleFrontierReached}
        onPlayRequest={resumePlayback}
        onPauseRequest={pausePlayback}
        onSeekRequest={commitSeek}
        onError={(message) => setError(message)}
      />

      <div className="player-topbar">
        <Link href="/" className="icon-button glass-button" aria-label="返回节目">
          <WaveIcon name="back" />
        </Link>
        <div className="player-grabber" />
        <details className="player-more-menu">
          <summary className="icon-button glass-button" aria-label="更多">
            <WaveIcon name="more" />
          </summary>
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
            <button
              type="button"
              onClick={() => void exportEpisode()}
              disabled={
                localEpisode.state !== "MATERIALIZED"
                || exportState === "preparing"
              }
            >
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
              : (
                  <button type="button" onClick={resumePlayback}>
                    恢复节目
                  </button>
                )}
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
        <p className="chapter-line">
          Chapter {currentChapterIndex + 1} · {chapterTitle}
        </p>
        <p className="track-line">
          {current?.kind === "MUSIC"
            ? [current.artist, current.title].filter(Boolean).join(" — ")
            : current?.title ?? "主持人正在串联"}
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
            seekPreviewRef.current = value;
            setSeekPreview(value);
          }}
          onPointerUp={commitSeekPreview}
          onPointerCancel={commitSeekPreview}
          onTouchEnd={commitSeekPreview}
          onTouchCancel={commitSeekPreview}
          onMouseUp={commitSeekPreview}
          onKeyUp={commitSeekPreview}
          onBlur={commitSeekPreview}
          style={{ "--played": playedPercent + "%" } as React.CSSProperties}
        />
        <div>
          <span>{formatSeconds(displayedPosition)}</span>
          <span>-{formatSeconds(remaining)}</span>
        </div>
      </section>

      <section className="transport-controls" aria-label="播放控制">
        <button
          type="button"
          className="transport-secondary"
          aria-label="后退 15 秒"
          onClick={() => nudgeSeek(-15)}
        >
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
        <button
          type="button"
          className="transport-secondary"
          aria-label="前进 30 秒"
          onClick={() => nudgeSeek(30)}
        >
          <WaveIcon name="skipForward" size={27} />
        </button>
      </section>

      <section className="player-utilities">
        <button
          type="button"
          className="utility-button"
          onClick={() => setChaptersOpen(true)}
        >
          <WaveIcon name="list" size={21} />
          <span>节目时间轴</span>
        </button>
        <button
          type="button"
          className="utility-button"
          onClick={nextPlayback}
        >
          <WaveIcon name="chevron" size={21} />
          <span>下一章节</span>
        </button>
      </section>

      {programBuffering ? (
        <div className="preparing-hint">
          <i />正在缓冲节目音频
        </div>
      ) : preparingAhead ? (
        <div className="preparing-hint">
          <i />正在准备接下来的节目音频
        </div>
      ) : upcoming ? (
        <div className="up-next">
          接下来：<strong>{upcoming.title}</strong>
          {upcoming.artist ? " · " + upcoming.artist : ""}
        </div>
      ) : null}

      {error ? <p className="player-error">{error}</p> : null}
      {exportError ? <p className="player-error">{exportError}</p> : null}
      {exportArtifact ? (
        <a
          className="export-download"
          href={exportArtifact.audioUrl}
          download={downloadFilename(exportArtifact.episodeId)}
        >
          再次下载 MP3
        </a>
      ) : null}

      <ChaptersSheet
        episode={localEpisode}
        currentSegmentId={current?.id ?? null}
        open={chaptersOpen}
        onClose={() => setChaptersOpen(false)}
      />
    </main>
  );
}
