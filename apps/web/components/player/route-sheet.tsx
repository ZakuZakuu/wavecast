"use client";

import { formatClock, routeChapters, type RouteChapter } from "../../lib/now-playing";
import { sourceNoticeText } from "../../lib/source-notice";
import { BottomSheet } from "../bottom-sheet";
import { CloseIcon } from "../icons";
import type { NowPlaying } from "./playback-provider";

const STATUS_LABEL = { playing: "正在播", ready: "已准备", preparing: "准备中" } as const;

/** Songs and host speech of each chapter, one row each with its start time. */
export function RouteList({ chapters, onJump }: { chapters: RouteChapter[]; onJump: (startSeconds: number) => void }) {
  return (
    <ol className="route-list">
      {chapters.map((chapter) => (
        <li key={chapter.id} className={"route-chapter is-" + chapter.status}>
          <div className="route-chapter-head">
            <span className="route-chapter-title">{chapter.title}</span>
            <span className="route-status">{STATUS_LABEL[chapter.status]}</span>
          </div>
          {chapter.tracks.map((track) => {
            const voice = track.kind === "VOICE";
            const content = (
              <>
                {voice && !track.playing ? (
                  <span className="route-voice-dot" aria-hidden="true" />
                ) : (
                  <span className="route-eq" aria-hidden="true">
                    {track.playing ? <><i /><i /><i /></> : null}
                  </span>
                )}
                <span className="route-track-name">{track.label}</span>
                {track.startSeconds !== null ? <span className="route-time tabular">{formatClock(track.startSeconds)}</span> : null}
              </>
            );
            return track.ready && track.startSeconds !== null && !track.playing ? (
              <button
                type="button"
                key={track.id}
                className={voice ? "route-track is-voice is-ready" : "route-track is-ready"}
                onClick={() => onJump(track.startSeconds!)}
              >
                {content}
              </button>
            ) : (
              <div
                key={track.id}
                className={(voice ? "route-track is-voice " : "route-track ") + (track.playing ? "is-playing" : track.ready ? "is-ready" : "is-pending")}
                aria-current={track.playing || undefined}
              >
                {content}
              </div>
            );
          })}
        </li>
      ))}
    </ol>
  );
}

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
    ? routeChapters(episode, playback.mixPlan, currentMusicId, playback.maxSeekPosition, playback.browserPosition)
    : [];
  const notice = sourceNoticeText(episode.source_notice);

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
      {notice ? <p className="route-notice">{notice}</p> : null}

      <RouteList
        chapters={chapters}
        onJump={(startSeconds) => {
          playback.commitSeek(startSeconds);
          if (!playback.browserPlaying) playback.resumePlayback();
          onClose();
        }}
      />

      <p className="route-foot">后面的章节会在你听的时候准备好，曲目可能会微调。</p>
    </BottomSheet>
  );
}
