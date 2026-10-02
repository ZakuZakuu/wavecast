"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { isDarkColour } from "../../lib/cover/build-cover";
import { readCaptionsEnabled, recordLessLikeThis, writeCaptionsEnabled } from "../../lib/listener-feedback";
import { friendlyError } from "../../lib/friendly-error";
import { lastTabPathOr } from "../../lib/nav-memory";
import { currentMusicSegment, estimatedTotalSeconds } from "../../lib/now-playing";
import { nextProgramMusicStart } from "../../lib/playback";
import { formatFreq } from "../../lib/stations";
import { TypeCover } from "../cover/type-cover";
import { Back15Icon, CaptionsIcon, ChevronDownIcon, MoreIcon, PauseIcon, PlayIcon, RouteIcon, SkipIcon, ThumbDownIcon } from "../icons";
import { MoreSheet } from "./more-sheet";
import { useNowPlaying, usePlaybackControl, usePlaybackTarget } from "./playback-provider";
import { ProgressBar } from "./progress-bar";
import { RouteSheet } from "./route-sheet";

const CAPTION_LINGER_MS = 1500;

function useToast() {
  const [message, setMessage] = useState<string | null>(null);
  const timer = useRef<number | null>(null);
  const show = useCallback((text: string) => {
    setMessage(text);
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setMessage(null), 2200);
  }, []);
  useEffect(() => () => {
    if (timer.current !== null) window.clearTimeout(timer.current);
  }, []);
  return { message, show };
}

export function PlayerScreen({ seedId, episodeId }: { seedId?: string; episodeId?: string }) {
  usePlaybackTarget({ seedId, episodeId });
  const router = useRouter();
  const playback = useNowPlaying();
  const { reload } = usePlaybackControl();
  const toast = useToast();
  const [routeOpen, setRouteOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const [captions, setCaptions] = useState(true);
  const [caption, setCaption] = useState<{ text: string | null } | null>(null);
  const swipeRef = useRef<number | null>(null);

  useEffect(() => setCaptions(readCaptionsEnabled()), []);

  const matches = playback?.localEpisode && (
    episodeId ? playback.localEpisode.id === episodeId : playback.localEpisode.seed_id === seedId
  );
  const np = matches ? playback : null;
  const episode = np?.localEpisode ?? null;

  const collapse = useCallback(() => {
    router.push(lastTabPathOr("/"));
  }, [router]);

  // Caption bar: follows the current narration and lingers 1.5s after it ends.
  const narration = np?.current?.kind === "NARRATION" ? np.current : null;
  const narrationKey = narration?.id ?? null;
  const narrationText = narration?.narration_text?.trim() || null;
  useEffect(() => {
    if (narrationKey) {
      setCaption({ text: narrationText });
      return;
    }
    const timer = window.setTimeout(() => setCaption(null), CAPTION_LINGER_MS);
    return () => window.clearTimeout(timer);
  }, [narrationKey, narrationText]);

  const music = useMemo(
    () => episode && np ? currentMusicSegment(episode, np.mixPlan, np.browserPosition, np.current) : undefined,
    [episode, np],
  );

  if (!np || !episode) {
    // A start that failed before any episode existed still reports here.
    const sameTarget = Boolean(playback && (
      episodeId ? playback.target.episodeId === episodeId : playback.target.seedId === seedId
    ));
    const failed = Boolean(sameTarget && playback?.error && !playback.localEpisode);
    return (
      <main className="player player-loading" aria-busy={!failed}>
        <div className="player-body">
          <div className="player-top">
            <button type="button" className="glass-icon" aria-label="收起" onClick={collapse}>
              <ChevronDownIcon size={20} strokeWidth={2.2} />
            </button>
          </div>
          <div className="player-cover-slot"><div className="player-cover-placeholder" /></div>
          <p className="player-loading-text" role="status">
            {failed ? friendlyError(playback?.error, "节目暂时无法开始，可以再试一次") : "正在接入节目…"}
          </p>
          {failed ? (
            <div className="player-failed-actions">
              <button type="button" className="pill-button on-dark" onClick={reload}>重试</button>
              <Link href="/tune" className="pill-button on-dark">回到调频</Link>
            </div>
          ) : null}
        </div>
      </main>
    );
  }

  const station = np.station;
  const cover = np.cover;
  const manifest = np.programManifest;
  const audioReady = Boolean(manifest && manifest.chunks.length > 0 && manifest.renderedFrontierSeconds > 0);
  const frontier = np.maxSeekPosition;
  const total = estimatedTotalSeconds(episode, manifest);
  const darkCover = cover ? isDarkColour(cover.params.bg) : true;
  const preparingHint = np.programBuffering || np.preparingAhead || !audioReady;

  const skip = () => {
    const target = np.mixPlan ? nextProgramMusicStart(np.mixPlan, np.browserPosition) : undefined;
    if (target === undefined || target >= frontier) {
      toast.show("下一首还在准备");
      return;
    }
    np.nextPlayback();
  };

  const lessLikeThis = () => {
    if (music) {
      recordLessLikeThis({ trackRef: music.track_ref, title: music.title, artist: music.artist, episodeId: episode.id });
    }
    toast.show("会少放这类歌");
  };

  const toggleCaptions = () => {
    setCaptions((value) => {
      writeCaptionsEnabled(!value);
      return !value;
    });
  };

  const showCaptionBar = Boolean(caption);
  const showPreparing = !showCaptionBar && preparingHint;

  return (
    <main className="player page-rise" data-cover-tone={darkCover ? "dark" : "light"}>
      {cover ? (
        <div className="player-backdrop" aria-hidden="true">
          <div className="player-backdrop-art">
            <TypeCover params={{ ...cover.params, bare: true }} radius={0} />
          </div>
          <span className="player-backdrop-shade" />
        </div>
      ) : null}

      <div className="player-body">
        <div
          className="player-top-zone"
          onPointerDown={(event) => { swipeRef.current = event.clientY; }}
          onPointerUp={(event) => {
            if (swipeRef.current !== null && event.clientY - swipeRef.current > 80) collapse();
            swipeRef.current = null;
          }}
          onPointerCancel={() => { swipeRef.current = null; }}
        >
          <span className="player-grabber" aria-hidden="true" />
          <div className="player-top">
            <button type="button" className="glass-icon" aria-label="收起" onClick={collapse}>
              <ChevronDownIcon size={20} strokeWidth={2.2} />
            </button>
            {station ? (
              <span className="station-pill">
                <span className="live-dot" aria-hidden="true" />
                <span className="station-pill-freq tabular">FM {formatFreq(station.freq)}</span>
                <span>{station.name}</span>
              </span>
            ) : <span />}
            <button type="button" className="glass-icon" aria-label="更多操作" onClick={() => setMoreOpen(true)}>
              <MoreIcon size={20} />
            </button>
          </div>
        </div>

        <div className="player-cover-slot">
          {cover ? (
            <div className="player-cover">
              <TypeCover params={cover.params} radius={12} />
            </div>
          ) : null}
        </div>
        {cover?.titleBelow ? <p className="player-programme-title">{episode.title}</p> : null}

        <div className="player-meta">
          <div className="player-meta-text">
            <h1>{music?.title || episode.title || "WaveCast"}</h1>
            <p>{music?.artist ?? station?.name ?? ""}</p>
          </div>
          <button type="button" className="glass-icon" aria-label="少放这类" onClick={lessLikeThis}>
            <ThumbDownIcon size={20} strokeWidth={1.8} />
          </button>
        </div>

        <div className="player-caption-slot" aria-live="polite">
          {showCaptionBar ? (
            <div className={narrationKey ? "caption-bar is-open" : "caption-bar is-closing"}>
              <span className="caption-label">
                <span className="voice-bars" aria-hidden="true"><i /><i /><i /><i /><i /></span>
                主持在说
              </span>
              {captions && caption?.text ? <p>{caption.text}</p> : null}
            </div>
          ) : showPreparing ? (
            <div className="caption-bar is-open is-hint">
              <span className="caption-label">正在准备接下来的内容</span>
            </div>
          ) : null}
        </div>

        <ProgressBar
          position={np.displayedPosition}
          frontier={frontier}
          total={total}
          disabled={!audioReady}
          onPreview={np.updateSeekPreview}
          onCommit={np.commitSeek}
          onOvershoot={() => toast.show("这部分还在准备")}
        />

        <div className="transport" aria-label="播放控制">
          <button type="button" className="transport-side" aria-label="后退 15 秒" onClick={() => np.nudgeSeek(-15)} disabled={!audioReady}>
            <Back15Icon size={34} />
          </button>
          <button
            type="button"
            className="transport-main"
            aria-label={np.browserPlaying ? "暂停" : "播放"}
            onClick={np.browserPlaying ? np.pausePlayback : np.resumePlayback}
          >
            <span className="morph" data-state={np.browserPlaying ? "pause" : "play"}>
              <PlayIcon size={46} className="morph-play" />
              <PauseIcon size={46} className="morph-pause" />
            </span>
          </button>
          <button type="button" className="transport-side" aria-label="跳过这首" onClick={skip} disabled={!audioReady}>
            <SkipIcon size={34} />
          </button>
        </div>

        {np.error ? <p className="player-error" role="alert">{np.error}</p> : null}
        {!audioReady && np.renderState === "error" ? (
          <button type="button" className="pill-button on-dark" onClick={np.requestProgramRender}>重试准备</button>
        ) : null}

        <div className="player-bottom">
          <button
            type="button"
            className={captions ? "bottom-tool is-on" : "bottom-tool"}
            aria-label="字幕"
            aria-pressed={captions}
            onClick={toggleCaptions}
          >
            <CaptionsIcon size={22} strokeWidth={1.8} />
          </button>
          <button type="button" className="bottom-tool" aria-label="节目路线" onClick={() => setRouteOpen(true)}>
            <RouteIcon size={22} strokeWidth={1.8} />
          </button>
        </div>
      </div>

      {toast.message ? <div className="toast" role="status">{toast.message}</div> : null}

      <RouteSheet
        open={routeOpen}
        onClose={() => setRouteOpen(false)}
        playback={np}
        currentMusicId={music?.id ?? null}
        totalSeconds={total}
      />
      <MoreSheet open={moreOpen} onClose={() => setMoreOpen(false)} playback={np} />
    </main>
  );
}
