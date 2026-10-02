"use client";

import { downloadFilename } from "../../lib/episode-export";
import { BottomSheet } from "../bottom-sheet";
import { DownloadIcon, PlayIcon, SaveIcon, StopIcon } from "../icons";
import type { NowPlaying } from "./playback-provider";

export function MoreSheet({
  open,
  onClose,
  playback,
}: {
  open: boolean;
  onClose: () => void;
  playback: NowPlaying;
}) {
  const episode = playback.localEpisode;
  if (!episode) return null;
  const materialized = episode.state === "MATERIALIZED";
  const saveLabel = playback.saveState !== "idle"
    ? "正在准备完整节目…"
    : playback.saved
      ? "已保存到节目库"
      : materialized
        ? "保存到节目库"
        : "准备完整节目并保存";

  return (
    <BottomSheet open={open} onClose={onClose} label="更多操作" tone="light">
      <h2 className="visually-hidden">更多操作</h2>
      <div className="action-group">
        <button
          type="button"
          className="action-row"
          onClick={() => void playback.prepareAndSaveEpisode()}
          disabled={playback.saveState !== "idle" || playback.saved}
        >
          <SaveIcon size={22} />
          <span>{saveLabel}</span>
        </button>
        <button
          type="button"
          className="action-row"
          onClick={() => void playback.exportEpisode()}
          disabled={!materialized || playback.exportState === "preparing"}
        >
          <DownloadIcon size={22} />
          <span>
            {playback.exportState === "preparing" ? "正在准备导出…" : "导出 MP3"}
            {!materialized ? <small>完整节目准备好后可以导出</small> : null}
          </span>
        </button>
        {episode.is_listener_active ? (
          <button type="button" className="action-row" onClick={() => { playback.leaveEpisode(); onClose(); }}>
            <StopIcon size={22} />
            <span>
              {episode.state === "MATERIALIZING" ? "停止播放（完整节目继续准备）" : "停止后台准备"}
              <small>已经准备好的部分会保留</small>
            </span>
          </button>
        ) : (
          <button type="button" className="action-row" onClick={() => { playback.resumePlayback(); onClose(); }}>
            <PlayIcon size={22} />
            <span>恢复后台准备</span>
          </button>
        )}
      </div>
      {playback.exportError ? <p className="sheet-note is-error">{playback.exportError}</p> : null}
      {playback.exportArtifact ? (
        <a className="sheet-link" href={playback.exportArtifact.audioUrl} download={downloadFilename(playback.exportArtifact.episodeId)}>
          再次下载 MP3
        </a>
      ) : null}
      <button type="button" className="sheet-cancel" onClick={onClose}>取消</button>
    </BottomSheet>
  );
}
