"use client";

import Link from "next/link";
import { useLayoutEffect, useRef, useState } from "react";

import { currentMusicSegment, estimatedTotalSeconds, formatClock } from "../lib/now-playing";
import { nextProgramMusicStart } from "../lib/playback";
import { formatFreq } from "../lib/stations";
import { TypeCover } from "./cover/type-cover";
import { PauseIcon, PlayIcon, SkipIcon } from "./icons";
import { openPlayer } from "../lib/player-nav";
import { useNowPlaying } from "./player/playback-provider";

// Programme whose entrance has already been animated (survives remounts).
let lastEnteredEpisodeId: string | null = null;

/**
 * Floating mini player, rendered once app-wide. `hidden` keeps it mounted but
 * invisible (player route, 开播中) so showing it again does not replay the
 * entrance animation; that only runs when a new programme appears.
 */
export function MiniPlayer({ hidden = false }: { hidden?: boolean }) {
  const np = useNowPlaying();
  const swipeRef = useRef<number | null>(null);
  const episode = np?.localEpisode;
  const episodeId = episode?.id ?? null;
  const [entering, setEntering] = useState(false);

  // Layout effect: the entering class applies before the first paint.
  useLayoutEffect(() => {
    if (!episodeId || hidden || lastEnteredEpisodeId === episodeId) return;
    lastEnteredEpisodeId = episodeId;
    setEntering(true);
  }, [episodeId, hidden]);

  if (!np || !episode) return null;

  const href = `/episode/materialized/${episode.id}`;
  const music = currentMusicSegment(episode, np.mixPlan, np.browserPosition, np.current);
  const total = estimatedTotalSeconds(episode, np.programManifest);
  const played = Math.min(100, (np.browserPosition / Math.max(1, total)) * 100);
  const nextStart = np.mixPlan ? nextProgramMusicStart(np.mixPlan, np.browserPosition) : undefined;
  const canSkip = nextStart !== undefined && nextStart < np.maxSeekPosition;

  return (
    <div
      className={entering ? "mini-player is-entering" : "mini-player"}
      hidden={hidden}
      aria-hidden={hidden || undefined}
      onAnimationEnd={() => setEntering(false)}
      onPointerDown={(event) => { swipeRef.current = event.clientY; }}
      onPointerUp={(event) => {
        if (swipeRef.current !== null && swipeRef.current - event.clientY > 40) openPlayer(href, "mini");
        swipeRef.current = null;
      }}
    >
      <span className="mini-progress" aria-hidden="true"><span style={{ transform: `scaleX(${played / 100})` }} /></span>
      <Link
        href={href}
        className="mini-main"
        aria-label="展开播放页"
        onClick={(event) => {
          if (event.metaKey || event.ctrlKey || event.shiftKey) return;
          event.preventDefault();
          openPlayer(href, "mini");
        }}
      >
        <span className="mini-cover">
          {np.cover ? <TypeCover params={{ ...np.cover.params, bare: true }} radius={0} /> : null}
        </span>
        <span className="mini-copy">
          <strong>{music?.title || episode.title || "WaveCast"}</strong>
          <small>
            {np.browserPlaying ? (
              <>
                <span className="live-dot" aria-hidden="true" />
                {np.station ? `FM ${formatFreq(np.station.freq)} ${np.station.name}` : "WaveCast"}
              </>
            ) : (
              <span className="tabular">暂停在 {formatClock(np.browserPosition)}</span>
            )}
          </small>
        </span>
      </Link>
      <button
        type="button"
        className="mini-button"
        aria-label={np.browserPlaying ? "暂停" : "播放"}
        onClick={np.browserPlaying ? np.pausePlayback : np.resumePlayback}
      >
        <span className="morph morph-sm" data-state={np.browserPlaying ? "pause" : "play"}>
          <PlayIcon size={24} className="morph-play" />
          <PauseIcon size={24} className="morph-pause" />
        </span>
      </button>
      <button type="button" className="mini-button" aria-label="跳过这首" onClick={np.nextPlayback} disabled={!canSkip}>
        <SkipIcon size={24} />
      </button>
    </div>
  );
}
