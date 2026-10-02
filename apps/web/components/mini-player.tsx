"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef } from "react";

import { currentMusicSegment, estimatedTotalSeconds } from "../lib/now-playing";
import { nextProgramMusicStart } from "../lib/playback";
import { formatFreq } from "../lib/stations";
import { TypeCover } from "./cover/type-cover";
import { PauseIcon, PlayIcon, SkipIcon } from "./icons";
import { useNowPlaying } from "./player/playback-provider";

/** Floating mini player; only shown while a programme is loaded. */
export function MiniPlayer() {
  const np = useNowPlaying();
  const router = useRouter();
  const swipeRef = useRef<number | null>(null);
  const episode = np?.localEpisode;
  if (!np || !episode) return null;

  const href = `/episode/materialized/${episode.id}`;
  const music = currentMusicSegment(episode, np.mixPlan, np.browserPosition, np.current);
  const total = estimatedTotalSeconds(episode, np.programManifest);
  const played = Math.min(100, (np.browserPosition / Math.max(1, total)) * 100);
  const nextStart = np.mixPlan ? nextProgramMusicStart(np.mixPlan, np.browserPosition) : undefined;
  const canSkip = nextStart !== undefined && nextStart < np.maxSeekPosition;

  return (
    <div
      className="mini-player"
      onPointerDown={(event) => { swipeRef.current = event.clientY; }}
      onPointerUp={(event) => {
        if (swipeRef.current !== null && swipeRef.current - event.clientY > 40) router.push(href);
        swipeRef.current = null;
      }}
    >
      <span className="mini-progress" aria-hidden="true"><span style={{ width: played + "%" }} /></span>
      <Link href={href} className="mini-main" aria-label="展开播放页">
        <span className="mini-cover">
          {np.cover ? <TypeCover params={{ ...np.cover.params, bare: true }} radius={0} /> : null}
        </span>
        <span className="mini-copy">
          <strong>{music?.title || episode.title || "WaveCast"}</strong>
          <small>
            <span className="live-dot" aria-hidden="true" />
            {np.station ? `FM ${formatFreq(np.station.freq)} ${np.station.name}` : "WaveCast"}
          </small>
        </span>
      </Link>
      <button
        type="button"
        className="mini-button"
        aria-label={np.browserPlaying ? "暂停" : "播放"}
        onClick={np.browserPlaying ? np.pausePlayback : np.resumePlayback}
      >
        {np.browserPlaying ? <PauseIcon size={24} /> : <PlayIcon size={24} />}
      </button>
      <button type="button" className="mini-button" aria-label="跳过这首" onClick={np.nextPlayback} disabled={!canSkip}>
        <SkipIcon size={24} />
      </button>
    </div>
  );
}
