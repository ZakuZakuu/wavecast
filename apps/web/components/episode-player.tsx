"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "../lib/api";
import { subscribeToEpisodeEvents } from "../lib/episode-events";
import { createEffectGenerationGuard, createIndependentSynchronizationTasks, createSynchronizationGuard } from "../lib/episode-synchronization";
import { downloadFilename, ExportBlockedError, prepareEpisodeExport, triggerMixdownDownload, type MixdownArtifact } from "../lib/episode-export";
import { formatSeconds, isProgramPlaybackComplete, isSeekAllowed, nextVisibleSegment, playbackAnchor, reconcileBrowserPosition, segmentOffset, segmentStart } from "../lib/playback";
import { usePlayerStore } from "../lib/player-store";
import type { LiveEpisode } from "../lib/types";
import { isEpisodeSaved, recordRecentEpisode, saveMaterializedEpisode } from "../lib/user-library";
import { ChaptersSheet } from "./chapters-sheet";
import { AudioPlayer } from "./audio-player";
import { ProgramArtwork } from "./program-artwork";
import { WaveIcon } from "./wave-icon";

const CHAPTER_TITLES = ["开场", "夜色开始变暖", "从旋律走进城市", "另一面的节奏", "慢慢收回来"];

export function EpisodePlayer({ seedId, episodeId }: { seedId?: string; episodeId?: string }) {
  const { episode, setEpisode } = usePlayerStore();
  const [error, setError] = useState<string | null>(null);
  const [browserPosition, setBrowserPosition] = useState(0);
  const [browserPlaying, setBrowserPlaying] = useState(false);
  const [seekToken, setSeekToken] = useState(0);
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
  const awaitingSuccessorRef = useRef(false);
  const playbackAnchorRef = useRef<ReturnType<typeof playbackAnchor>>(null);
  const localEpisodeRef = useRef<LiveEpisode | null>(null);
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
  localEpisodeRef.current = localEpisode;

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
        void api.checkpoint(episodeIdRef.current, Math.floor(browserPositionRef.current));
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
    const isCurrent = () => synchronizationGuard.isCurrent(
      generation,
      localEpisodeRef.current?.is_listener_active ?? false,
    );
    let bufferFailed = false;
    const tasks = createIndependentSynchronizationTasks(
      async () => {
        if (!isCurrent()) return;
        try {
          await api.heartbeat(localEpisode.id);
        } catch {
          // Heartbeat is session liveness metadata. Never interrupt local audio
          // because a background liveness write raced with another server mutation.
        }
      },
      async () => {
        if (!isCurrent() || bufferFailed) return;
        const currentEpisode = localEpisodeRef.current;
        if (!currentEpisode || currentEpisode.state === "MATERIALIZED") return;
        try {
          const updated = await api.ensureBuffer(currentEpisode.id);
          if (isCurrent()) setEpisode(updated);
        } catch (reason) {
          bufferFailed = true;
          if (isCurrent()) {
            setError(reason instanceof Error ? reason.message : "接下来的章节生成失败");
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
    awaitingSuccessorRef.current = false;
    setBrowserPlaying(false);
    synchronizationGuardRef.current.invalidate();
    void update(api.leave(currentEpisode.id));
  }, []);

  const completeBrowserSegment = useCallback(() => {
    if (!localEpisode || !browserPlaying) return;

    // The source file may be much longer than the generated WaveCast segment.
    // Stop locally at the generated frontier first; never let the raw music file
    // continue while the next progressive chapter is still being prepared.
    setBrowserPlaying(false);

    void api.completed(localEpisode.id)
      .then((completed) => {
        setEpisode(completed);
        setError(null);

        if (isProgramPlaybackComplete(completed)) {
          awaitingSuccessorRef.current = false;
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
        }
      })
      .catch((reason: unknown) => {
        awaitingSuccessorRef.current = false;
        setError(reason instanceof Error ? reason.message : "操作暂时没有完成");
      });
  }, [browserPlaying, localEpisode, setEpisode]);

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
    const linearValue = value;
    if (!isSeekAllowed(localEpisode, linearValue)) {
      seekPreviewRef.current = null;
      setSeekPreview(null);
      return;
    }

    const currentStart = current ? segmentStart(localEpisode, current.id) : 0;
    const currentDuration = current
      ? current.duration_seconds ?? current.actual_duration_seconds ?? current.planned_duration_seconds
      : 0;
    const withinCurrent = Boolean(
      current
      && linearValue >= currentStart
      && linearValue < currentStart + currentDuration,
    );

    if (withinCurrent) {
      setBrowserPosition(linearValue);
      browserPositionRef.current = linearValue;
      setSeekToken((token) => token + 1);
      seekPreviewRef.current = null;
      setSeekPreview(null);
    }

    void api.seek(localEpisode.id, Math.floor(linearValue))
      .then((response) => {
        playbackAnchorRef.current = playbackAnchor(response);
        setEpisode(response);
        setBrowserPosition(linearValue);
        browserPositionRef.current = linearValue;
        if (!withinCurrent) setSeekToken((token) => token + 1);
        seekPreviewRef.current = null;
        setSeekPreview(null);
        setError(null);
      })
      .catch((reason: unknown) => {
        seekPreviewRef.current = null;
        setSeekPreview(null);
        setError(reason instanceof Error ? reason.message : "跳转暂时没有完成");
      });
  }, [current, localEpisode, setEpisode]);

  const commitSeekPreview = useCallback(() => {
    const preview = seekPreviewRef.current;
    if (preview !== null) commitSeek(preview);
  }, [commitSeek]);

  const pausePlayback = useCallback(() => {
    if (!localEpisode) return;
    awaitingSuccessorRef.current = false;
    setBrowserPlaying(false);
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

  const maxSeekPosition = localEpisode.generated_frontier_seconds;
  const fullDuration = localEpisode.timeline_duration_seconds;
  const generatedPercent = Math.min(100, Math.round((maxSeekPosition / Math.max(1, fullDuration)) * 100));
  const displayedPosition = seekPreview ?? browserPosition;
  const displayedLinearPosition = browserPosition;
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

  const nudgeSeek = (seconds: number) => {
    commitSeek(Math.max(0, browserPositionRef.current + seconds));
  };

  return (
    <main className="now-playing-page page-enter">
      <AudioPlayer
        segment={current}
        playing={browserPlaying && localEpisode.is_listener_active}
        positionSeconds={currentOffset}
        seekToken={seekToken}
        maxDurationSeconds={current
          ? current.duration_seconds ?? current.actual_duration_seconds ?? current.planned_duration_seconds
          : null}
        onPositionChange={handleAudioPosition}
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
            const linearValue = value;
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
