"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "../lib/api";
import { subscribeToEpisodeEvents } from "../lib/episode-events";
import { createEffectGenerationGuard, createIndependentSynchronizationTasks, createSynchronizationGuard } from "../lib/episode-synchronization";
import { downloadFilename, ExportBlockedError, prepareEpisodeExport, triggerMixdownDownload, type MixdownArtifact } from "../lib/episode-export";
import { createLatestSegmentCommitQueue, type LatestSegmentCommitQueue } from "../lib/mix-commit-queue";
import { linearPositionToMixPosition, mixPlanSignature, mixPositionToLinearPosition } from "../lib/mix-timeline";
import type { MixPlan } from "../lib/mix-timeline";
import { formatSeconds, isProgramPlaybackComplete, isSeekAllowed, nextVisibleSegment, playbackAnchor, reconcileBrowserPosition, segmentOffset, segmentStart } from "../lib/playback";
import { usePlayerStore } from "../lib/player-store";
import type { LiveEpisode } from "../lib/types";
import { isEpisodeSaved, recordRecentEpisode, saveMaterializedEpisode } from "../lib/user-library";
import { ChaptersSheet } from "./chapters-sheet";
import { MixAudioPlayer } from "./mix-audio-player";
import { ProgramArtwork } from "./program-artwork";
import { WaveIcon } from "./wave-icon";

const CHAPTER_TITLES = ["开场", "夜色开始变暖", "从旋律走进城市", "另一面的节奏", "慢慢收回来"];

export function EpisodePlayer({ seedId, episodeId }: { seedId?: string; episodeId?: string }) {
  const { episode, setEpisode } = usePlayerStore();
  const [error, setError] = useState<string | null>(null);
  const [browserPosition, setBrowserPosition] = useState(0);
  const [seekPreview, setSeekPreview] = useState<number | null>(null);
  const [chaptersOpen, setChaptersOpen] = useState(false);
  const [exportState, setExportState] = useState<"idle" | "preparing" | "ready" | "error">("idle");
  const [exportArtifact, setExportArtifact] = useState<MixdownArtifact | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [saveState, setSaveState] = useState<"idle" | "preparing">("idle");
  const episodeIdRef = useRef<string | null>(null);
  const checkpointRef = useRef<number>(-1);
  const browserPositionRef = useRef(0);
  const seekPreviewRef = useRef<number | null>(null);
  const playbackAnchorRef = useRef<ReturnType<typeof playbackAnchor>>(null);
  const localEpisodeRef = useRef<LiveEpisode | null>(null);
  const mixPlanRef = useRef<MixPlan | null>(null);
  const mixCommitQueueRef = useRef<LatestSegmentCommitQueue | null>(null);
  const startEffectGuardRef = useRef(createEffectGenerationGuard());
  const synchronizationGuardRef = useRef(createSynchronizationGuard());

  const localEpisode = episode
    && (episodeId ? episode.id === episodeId : episode.seed_id === seedId)
    ? episode
    : null;
  const current = useMemo(
    () => localEpisode?.segments.find((segment) => segment.id === localEpisode.current_segment_id),
    [localEpisode],
  );
  const [mixPlan, setMixPlan] = useState<MixPlan | null>(null);
  const mixPlanKey = localEpisode ? mixPlanSignature(localEpisode) : "";

  if (localEpisodeRef.current?.id !== localEpisode?.id) {
    mixCommitQueueRef.current?.reset();
    mixCommitQueueRef.current = null;
  }
  localEpisodeRef.current = localEpisode;
  mixPlanRef.current = mixPlan;

  if (!mixCommitQueueRef.current && localEpisode) {
    mixCommitQueueRef.current = createLatestSegmentCommitQueue({
      commit: (segmentId) => api.commit(localEpisode.id, segmentId),
      isCurrent: (segmentId) => localEpisodeRef.current?.current_segment_id === segmentId,
      onResponse: (response) => {
        playbackAnchorRef.current = playbackAnchor(response);
        setEpisode(response);
        setBrowserPosition(browserPositionRef.current);
        setError(null);
      },
      onError: (reason) => {
        setError(reason instanceof Error ? reason.message : "播放同步失败");
      },
    });
  }

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
      const plan = mixPlanRef.current;
      if (episodeIdRef.current && currentEpisode) {
        const transport = plan
          ? mixPositionToLinearPosition(currentEpisode, plan, browserPositionRef.current)
          : { linearPositionSeconds: browserPositionRef.current };
        void api.checkpoint(episodeIdRef.current, Math.floor(transport.linearPositionSeconds));
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
      if (mounted) setEpisode(started);
      else deferLeave(started.id);
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
  }, [localEpisode?.id, localEpisode?.version, current?.title]);

  useEffect(() => {
    if (!localEpisode || !mixPlanKey) {
      setMixPlan(null);
      return undefined;
    }
    let active = true;
    void api.mixPlan(localEpisode.id)
      .then((plan) => {
        if (active) setMixPlan(plan);
      })
      .catch(() => {
        if (active) setMixPlan(null);
      });
    return () => {
      active = false;
    };
  }, [localEpisode?.id, mixPlanKey]);

  useEffect(() => {
    const linearPosition = reconcileBrowserPosition(
      browserPositionRef.current,
      playbackAnchorRef.current,
      localEpisode,
    );
    const position = localEpisode && mixPlanRef.current
      ? linearPositionToMixPosition(localEpisode, mixPlanRef.current, linearPosition).mixPositionSeconds
      : linearPosition;
    if (seekPreviewRef.current === null) {
      setBrowserPosition(position);
      browserPositionRef.current = position;
    }
    playbackAnchorRef.current = playbackAnchor(localEpisode);
  }, [localEpisode?.current_segment_id, localEpisode?.playback_position_seconds, mixPlanKey]);

  useEffect(() => {
    if (!localEpisode?.is_listener_active) return;
    const synchronizationGuard = synchronizationGuardRef.current;
    const generation = synchronizationGuard.start();
    const isCurrent = () => synchronizationGuard.isCurrent(
      generation,
      localEpisodeRef.current?.is_listener_active ?? false,
    );
    const tasks = createIndependentSynchronizationTasks(
      async () => {
        if (!isCurrent()) return;
        try {
          await api.heartbeat(localEpisode.id);
        } catch (reason) {
          if (isCurrent()) {
            setError(reason instanceof Error ? reason.message : "播放同步失败");
          }
        }
      },
      async () => {
        if (!isCurrent()) return;
        const currentEpisode = localEpisodeRef.current;
        if (!currentEpisode || currentEpisode.state === "MATERIALIZED") return;
        try {
          const updated = await api.ensureBuffer(currentEpisode.id);
          if (isCurrent()) setEpisode(updated);
        } catch (reason) {
          if (isCurrent()) {
            setError(reason instanceof Error ? reason.message : "播放同步失败");
          }
        }
      },
    );

    void tasks.heartbeat();
    void tasks.buffer();
    const heartbeatInterval = window.setInterval(() => void tasks.heartbeat(), 10_000);
    const bufferInterval = window.setInterval(() => void tasks.buffer(), 10_000);
    return () => {
      synchronizationGuard.invalidate();
      window.clearInterval(heartbeatInterval);
      window.clearInterval(bufferInterval);
    };
  }, [localEpisode?.id, localEpisode?.is_listener_active, setEpisode]);

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
    synchronizationGuardRef.current.invalidate();
    void update(api.leave(currentEpisode.id));
  }, []);

  const completeBrowserSegment = useCallback(() => {
    if (!localEpisode?.is_playing) return;
    void api.completed(localEpisode.id)
      .then((completed) => {
        setEpisode(completed);
        setError(null);
        if (isProgramPlaybackComplete(completed)) {
          void api.recordUserEvent({
            event_type: "PLAY_COMPLETE",
            program_id: completed.seed_id,
            episode_id: completed.id,
          }).catch(() => undefined);
        }
      })
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : "操作暂时没有完成");
      });
  }, [localEpisode?.id, localEpisode?.is_playing, setEpisode]);

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

  const prepareAndSaveEpisode = useCallback(async () => {
    if (!localEpisode || saveState === "preparing" || saved) return;
    setSaveState("preparing");
    try {
      const ready = localEpisode.state === "MATERIALIZED"
        ? localEpisode
        : await api.materialize(localEpisode.id);
      if (ready !== localEpisode) setEpisode(ready);
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
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "保存节目失败，请稍后重试");
    } finally {
      setSaveState("idle");
    }
  }, [current?.title, localEpisode, saveState, saved, setEpisode]);

  const handleMixPosition = useCallback((positionSeconds: number) => {
    if (!localEpisode || !mixPlanRef.current || seekPreviewRef.current !== null) return;
    const transport = mixPositionToLinearPosition(localEpisode, mixPlanRef.current, positionSeconds);
    const linearPosition = Math.floor(transport.linearPositionSeconds);
    setBrowserPosition(positionSeconds);
    browserPositionRef.current = positionSeconds;

    if (transport.segmentId && transport.segmentId !== localEpisode.current_segment_id) {
      mixCommitQueueRef.current?.request(transport.segmentId);
    }

    if (
      transport.segmentId === localEpisode.current_segment_id
      && linearPosition > localEpisode.playback_position_seconds
      && linearPosition % 5 === 0
      && checkpointRef.current !== linearPosition
    ) {
      checkpointRef.current = linearPosition;
      void api.checkpoint(localEpisode.id, linearPosition);
    }
  }, [localEpisode]);

  const handleAudioPosition = useCallback((segmentPosition: number) => {
    if (!localEpisode || !current || seekPreviewRef.current !== null) return;
    const position = Math.floor(segmentStart(localEpisode, current.id) + Math.max(0, segmentPosition));
    setBrowserPosition(position);
    browserPositionRef.current = position;
    if (position > localEpisode.playback_position_seconds && position % 5 === 0 && checkpointRef.current !== position) {
      checkpointRef.current = position;
      void api.checkpoint(localEpisode.id, position);
    }
  }, [current, localEpisode]);

  const commitSeek = useCallback((value: number) => {
    if (!localEpisode) return;
    const linearValue = mixPlanRef.current
      ? mixPositionToLinearPosition(localEpisode, mixPlanRef.current, value).linearPositionSeconds
      : value;
    if (!isSeekAllowed(localEpisode, linearValue)) {
      seekPreviewRef.current = null;
      setSeekPreview(null);
      return;
    }
    const runSeek = async () => {
      const response = await api.seek(localEpisode.id, Math.floor(linearValue));
      mixCommitQueueRef.current?.acknowledge(response.current_segment_id);
      const mixValue = mixPlanRef.current
        ? linearPositionToMixPosition(localEpisode, mixPlanRef.current, linearValue).mixPositionSeconds
        : value;
      setBrowserPosition(mixValue);
      browserPositionRef.current = mixValue;
      playbackAnchorRef.current = playbackAnchor(response);
      setEpisode(response);
      seekPreviewRef.current = null;
      setSeekPreview(null);
      setError(null);
    };
    void (mixCommitQueueRef.current ? mixCommitQueueRef.current.runExclusive(runSeek) : runSeek())
      .catch((reason: unknown) => {
        seekPreviewRef.current = null;
        setSeekPreview(null);
        setError(reason instanceof Error ? reason.message : "跳转暂时没有完成");
      });
  }, [localEpisode, setEpisode]);

  const commitSeekPreview = useCallback(() => {
    const preview = seekPreviewRef.current;
    if (preview !== null) commitSeek(preview);
  }, [commitSeek]);

  const pausePlayback = useCallback(async () => {
    if (!localEpisode) return;
    const runPause = async () => {
      const currentEpisode = localEpisodeRef.current ?? localEpisode;
      const transport = mixPlanRef.current
        ? mixPositionToLinearPosition(currentEpisode, mixPlanRef.current, browserPositionRef.current)
        : { linearPositionSeconds: browserPositionRef.current, segmentId: currentEpisode.current_segment_id };
      let checkpointEpisode = currentEpisode;
      if (transport.segmentId && transport.segmentId !== currentEpisode.current_segment_id) {
        checkpointEpisode = await api.commit(currentEpisode.id, transport.segmentId);
        mixCommitQueueRef.current?.acknowledge(checkpointEpisode.current_segment_id);
        playbackAnchorRef.current = playbackAnchor(checkpointEpisode);
        setEpisode(checkpointEpisode);
      }
      const checkpointed = await api.checkpoint(checkpointEpisode.id, Math.floor(transport.linearPositionSeconds));
      setEpisode(checkpointed);
      const paused = await api.pause(checkpointEpisode.id);
      mixCommitQueueRef.current?.acknowledge(paused.current_segment_id);
      setEpisode(paused);
      setError(null);
    };
    try {
      await (mixCommitQueueRef.current ? mixCommitQueueRef.current.runExclusive(runPause) : runPause());
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "暂停暂时没有完成");
    }
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

  const maxSeekPosition = mixPlanRef.current
    ? linearPositionToMixPosition(localEpisode, mixPlanRef.current, localEpisode.generated_frontier_seconds).mixPositionSeconds
    : localEpisode.generated_frontier_seconds;
  const fullDuration = mixPlanRef.current?.durationSeconds ?? localEpisode.timeline_duration_seconds;
  const generatedPercent = Math.min(100, Math.round((maxSeekPosition / Math.max(1, fullDuration)) * 100));
  const displayedPosition = seekPreview ?? browserPosition;
  const displayedLinearPosition = mixPlanRef.current
    ? mixPositionToLinearPosition(localEpisode, mixPlanRef.current, browserPosition).linearPositionSeconds
    : browserPosition;
  const currentOffset = current
    ? segmentOffset(localEpisode, current.id, displayedLinearPosition)
    : 0;
  const upcoming = current ? nextVisibleSegment(localEpisode) : undefined;
  const chapterIds = Array.from(new Set(localEpisode.segments.map((segment) => segment.chapter_id)));
  const currentChapterIndex = Math.max(0, chapterIds.indexOf(current?.chapter_id ?? chapterIds[0]));
  const chapterTitle = CHAPTER_TITLES[currentChapterIndex] ?? "Chapter " + (currentChapterIndex + 1);
  const remaining = Math.max(0, fullDuration - displayedPosition);
  const preparingAhead = localEpisode.state !== "MATERIALIZED" && localEpisode.buffer_ahead_seconds < 45;

  const nextPlayback = async () => {
    const runNext = async () => {
      const response = await api.next(localEpisode.id);
      mixCommitQueueRef.current?.acknowledge(response.current_segment_id);
      setEpisode(response);
      setError(null);
      void api.recordUserEvent({
        event_type: "SKIP",
        program_id: response.seed_id,
        episode_id: response.id,
      }).catch(() => undefined);
    };
    try {
      await (mixCommitQueueRef.current ? mixCommitQueueRef.current.runExclusive(runNext) : runNext());
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "下一章节还没有准备好");
    }
  };

  const nudgeSeek = (seconds: number) => {
    commitSeek(Math.max(0, browserPositionRef.current + seconds));
  };

  return (
    <main className="now-playing-page page-enter">
      <MixAudioPlayer
        segment={current}
        plan={mixPlan}
        playing={localEpisode.is_playing && localEpisode.is_listener_active}
        positionSeconds={browserPosition}
        legacyPositionSeconds={currentOffset}
        onPositionChange={handleMixPosition}
        onLegacyPositionChange={handleAudioPosition}
        onEnded={completeBrowserSegment}
        onError={() => setError("音频暂时无法播放")}
      />

      <div className="player-topbar">
        <Link href="/" className="icon-button glass-button" aria-label="返回节目"><WaveIcon name="back" /></Link>
        <div className="player-grabber" />
        <details className="player-more-menu">
          <summary className="icon-button glass-button" aria-label="更多"><WaveIcon name="more" /></summary>
          <div className="player-more-popover">
            <button
              type="button"
              onClick={() => void prepareAndSaveEpisode()}
              disabled={saveState === "preparing" || saved}
            >
              {saveState === "preparing"
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
              ? <button type="button" onClick={leaveEpisode}>停止后台准备</button>
              : <button type="button" onClick={() => void update(api.resume(localEpisode.id))}>恢复节目</button>}
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
            const linearValue = mixPlanRef.current
              ? mixPositionToLinearPosition(localEpisode, mixPlanRef.current, value).linearPositionSeconds
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
          aria-label={localEpisode.is_playing ? "暂停" : "继续播放"}
          onClick={() => localEpisode.is_playing ? void pausePlayback() : void update(api.resume(localEpisode.id))}
        >
          <WaveIcon name={localEpisode.is_playing ? "pause" : "play"} size={30} />
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

      {preparingAhead ? (
        <div className="preparing-hint"><i />正在准备接下来的章节</div>
      ) : upcoming ? (
        <div className="up-next">接下来：<strong>{upcoming.title}</strong>{upcoming.artist ? " · " + upcoming.artist : ""}</div>
      ) : null}

      {error ? <p className="player-error">{error}</p> : null}
      {exportError ? <p className="player-error">{exportError}</p> : null}
      {exportArtifact ? <a className="export-download" href={exportArtifact.audioUrl} download={downloadFilename(exportArtifact.episodeId)}>再次下载 MP3</a> : null}

      <ChaptersSheet episode={localEpisode} open={chaptersOpen} onClose={() => setChaptersOpen(false)} />
    </main>
  );
}
