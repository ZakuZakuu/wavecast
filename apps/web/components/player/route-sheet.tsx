"use client";

import { formatClock, routeChapters } from "../../lib/now-playing";
import { BottomSheet } from "../bottom-sheet";
import { CloseIcon } from "../icons";
import type { NowPlaying } from "./playback-provider";

const STATUS_LABEL = { playing: "正在播", ready: "已准备", preparing: "准备中" } as const;

export function RouteSheet({
  open,
  onClose,
  playback,
  currentMusicId,
  totalSeconds,
}: {
  open: boolean;
  onClose: () => void;
  playback: NowPlaying;
  currentMusicId: string | null;
  totalSeconds: number;
}) {
  const episode = playback.localEpisode;
  if (!episode) return null;
  const chapters = open
    ? routeChapters(episode, playback.mixPlan, currentMusicId, playback.maxSeekPosition)
    : [];

  return (
    <BottomSheet open={open} onClose={onClose} label="节目路线" tone="dark" height="min(640px, calc(100dvh - 60px))">
      <header className="route-head">
        <div>
          <h2>节目路线</h2>
          <p>{episode.title ?? "WaveCast"}，约 {Math.max(1, Math.round(totalSeconds / 60))} 分钟</p>
        </div>
        <button type="button" className="route-close" aria-label="关闭" onClick={onClose}>
          <CloseIcon size={16} strokeWidth={2.4} />
        </button>
      </header>

      <ol className="route-list">
        {chapters.map((chapter) => (
          <li key={chapter.id} className={"route-chapter is-" + chapter.status}>
            <div className="route-chapter-head">
              <span className="route-chapter-title">
                <span className="route-time tabular">{chapter.startSeconds !== null ? formatClock(chapter.startSeconds) : "--:--"}</span>
                <span>{chapter.title}</span>
              </span>
              <span className="route-status">{STATUS_LABEL[chapter.status]}</span>
            </div>
            {chapter.tracks.map((track) => {
              const content = (
                <>
                  <span className="route-eq" aria-hidden="true">
                    {track.playing ? <><i /><i /><i /></> : null}
                  </span>
                  <span className="route-track-name">{track.label}</span>
                </>
              );
              return track.ready && track.startSeconds !== null && !track.playing ? (
                <button
                  type="button"
                  key={track.id}
                  className="route-track is-ready"
                  onClick={() => {
                    playback.commitSeek(track.startSeconds!);
                    if (!playback.browserPlaying) playback.resumePlayback();
                    onClose();
                  }}
                >
                  {content}
                </button>
              ) : (
                <div key={track.id} className={track.playing ? "route-track is-playing" : track.ready ? "route-track" : "route-track is-pending"} aria-current={track.playing || undefined}>
                  {content}
                </div>
              );
            })}
          </li>
        ))}
      </ol>

      <p className="route-foot">后面的章节会在你听的时候准备好，曲目可能会微调。</p>
    </BottomSheet>
  );
}
