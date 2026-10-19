"use client";

import { downloadFilename } from "../../lib/episode-export";
import { BottomSheet } from "../bottom-sheet";
import { DownloadIcon, InfoIcon, PlayIcon, ShareIcon, StopIcon } from "../icons";
import type { NowPlaying } from "./playback-provider";

/**
 * A sheet that closes by itself pops its own history entry a moment later; navigating or
 * opening another sheet before that happens would be undone by the pop.
 */
function afterSheetClosed(action: () => void): void {
  window.setTimeout(action, 320);
}

export function MoreSheet({
  open,
  onClose,
  playback,
  onDetail,
  onShare,
  onPrepareFull,
}: {
  open: boolean;
  onClose: () => void;
  playback: NowPlaying;
  /** Open the programme's own page. */
  onDetail: () => void;
  /** Open the share sheet for this programme. */
  onShare: () => void;
  /** Ask for the 完整版 of this programme (the player says how it went). */
  onPrepareFull: () => void;
}) {
  const episode = playback.localEpisode;
  if (!episode) return null;
  const materialized = episode.state === "MATERIALIZED";
  const fullLabel = playback.fullVersion === "ready"
    ? "完整版已准备好"
    : playback.fullVersion === "preparing"
      ? "准备中…"
      : "准备完整版";

  return (
    <BottomSheet open={open} onClose={onClose} label="更多操作" tone="light">
      <h2 className="visually-hidden">更多操作</h2>
      <div className="action-group">
        <button type="button" className="action-row" onClick={() => { onClose(); afterSheetClosed(onDetail); }}>
          <InfoIcon size={22} />
          <span>节目详情</span>
        </button>
        <button type="button" className="action-row" onClick={() => { onClose(); afterSheetClosed(onShare); }}>
          <ShareIcon size={22} />
          <span>分享这档节目</span>
        </button>
        <button
          type="button"
          className="action-row"
          onClick={() => { onClose(); onPrepareFull(); }}
          disabled={playback.fullVersion !== "none"}
        >
          <DownloadIcon size={22} />
          <span>{fullLabel}</span>
        </button>
        <button
          type="button"
          className="action-row"
          onClick={() => void playback.exportEpisode()}
          disabled={!materialized || playback.exportState === "preparing"}
        >
          <DownloadIcon size={22} />
          <span>{playback.exportState === "preparing" ? "正在准备导出…" : "导出 MP3"}</span>
        </button>
        {episode.is_listener_active ? (
          <button type="button" className="action-row" onClick={() => { playback.leaveEpisode(); onClose(); }}>
            <StopIcon size={22} />
            <span>{playback.fullVersion === "preparing" ? "停止播放（完整版继续准备）" : "停止后台准备"}</span>
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
