"use client";

import Link from "next/link";
import { useState } from "react";

import { downloadFilename } from "../lib/episode-export";
import { formatSeconds, musicChaptersForEpisode } from "../lib/playback";
import { useProgrammePlayback } from "../lib/use-programme-playback";
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

export function EpisodePlayer({
  seedId,
  episodeId,
}: {
  seedId?: string;
  episodeId?: string;
}) {
  const playback = useProgrammePlayback({ seedId, episodeId });
  const {
    localEpisode,
    error,
    programManifest,
    renderState,
    programBuffering,
    browserPlaying,
    browserPosition,
    seekToken,
    current,
    upcoming,
    exportState,
    exportArtifact,
    exportError,
    saved,
    saveState,
    requestProgramRender,
    leaveEpisode,
    exportEpisode,
    prepareAndSaveEpisode,
    handleProgramPosition,
    handlePlayingChange,
    setProgramBuffering,
    setError,
    commitSeek,
    updateSeekPreview,
    commitSeekPreview,
    pausePlayback,
    resumePlayback,
    handleProgrammeEnded,
    handleFrontierReached,
    nudgeSeek,
    nextPlayback,
    maxSeekPosition,
    displayedPosition,
    preparingAhead,
    mediaTitle,
    mediaArtist,
  } = playback;
  const [chaptersOpen, setChaptersOpen] = useState(false);

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
  const chapters = musicChaptersForEpisode(localEpisode);
  const currentChapterIndex = Math.max(
    0,
    chapters.findIndex((chapter) => chapter.segments.some((segment) => segment.id === current?.id)),
  );
  const chapterTitle = CHAPTER_TITLES[currentChapterIndex]
    ?? "Chapter " + (currentChapterIndex + 1);

  return (
    <main className="now-playing-page page-enter">
      <ProgrammeAudioPlayer
        streamUrl={programManifest.streamUrl}
        playing={browserPlaying && localEpisode.is_listener_active}
        positionSeconds={browserPosition}
        seekToken={seekToken}
        renderedFrontierSeconds={maxSeekPosition}
        complete={programManifest.complete}
        title={mediaTitle}
        artist={mediaArtist}
        onPositionChange={handleProgramPosition}
        onPlayingChange={handlePlayingChange}
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
          {current?.kind === "NARRATION"
            ? "主持串联"
            : `Chapter ${currentChapterIndex + 1} · ${chapterTitle}`}
        </p>
        <p className="track-line">
          {current?.kind === "MUSIC"
            ? [current.artist, current.title].filter(Boolean).join(" — ")
            : "主持人正在串联"}
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
            updateSeekPreview(Number(event.target.value));
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
