"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { isDarkColour } from "../../lib/cover/build-cover";
import { readCaptionsEnabled, recordLessLikeThis, writeCaptionsEnabled } from "../../lib/listener-feedback";
import { friendlyError } from "../../lib/friendly-error";
import { chapterNumberOf, currentMusicSegment, estimatedTotalSeconds, nextMusicSegment, trackLabel, voiceClipTiming } from "../../lib/now-playing";
import { currentSentenceIndex, nowLineMode, splitSentences, type NowLineMode } from "../../lib/now-line";
import { nextProgramMusicStart } from "../../lib/playback";
import { formatFreq } from "../../lib/stations";
import { TypeCover } from "../cover/type-cover";
import { Back15Icon, CaptionsIcon, ChevronDownIcon, MoreIcon, PauseIcon, PlayIcon, RouteIcon, SkipIcon, ThumbDownIcon } from "../icons";
import { MoreSheet } from "./more-sheet";
import { NarrationSheet } from "./narration-sheet";
import { NowLine } from "./now-line";
import { authClient } from "../../lib/auth-client";
import { useNowPlaying, usePlaybackControl, usePlaybackTarget } from "./playback-provider";
import { ProgressBar } from "./progress-bar";
import { RouteSheet } from "./route-sheet";

const COVER_MAX = 296;
const LAYOUT_SAMPLE = "这是一段用来检查布局的主持词。它比较长，用来确认字幕只显示两行。切换到下一句时会平滑上移！最后一句。";

/** Dev only: ?nowline=narration|preparing|next forces a NowLine state for layout checks. */
function forcedNowLineMode(): NowLineMode | null {
  if (process.env.NODE_ENV === "production" || typeof window === "undefined") return null;
  const value = new URLSearchParams(window.location.search).get("nowline");
  return value === "narration" || value === "preparing" || value === "next" ? value : null;
}

/** Cover = min(296, available height - 16, available width), recomputed on resize. */
function useCoverSize(extraBelow: number) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState(COVER_MAX);
  useEffect(() => {
    const element = ref.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setSize(Math.max(96, Math.floor(Math.min(COVER_MAX, height - 16 - extraBelow, width))));
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [extraBelow]);
  return { ref, size };
}

function useToast() {
  const [message, setMessage] = useState<string | null>(null);
  const timer = useRef<number | null>(null);
  const show = useCallback((text: string, durationMs = 2200) => {
    setMessage(text);
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setMessage(null), durationMs);
  }, []);
  useEffect(() => () => {
    if (timer.current !== null) window.clearTimeout(timer.current);
  }, []);
  return { message, show };
}

export function PlayerScreen({
  seedId,
  episodeId,
  onCollapse,
}: {
  seedId?: string;
  episodeId?: string;
  /** Collapse back to the mini player (the overlay animates it). */
  onCollapse: () => void;
}) {
  usePlaybackTarget({ seedId, episodeId });
  const playback = useNowPlaying();
  const { reload } = usePlaybackControl();
  const toast = useToast();
  const signedIn = Boolean(authClient.useSession().data?.user);
  const [routeOpen, setRouteOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const [captions, setCaptions] = useState(true);
  const [narrationOpen, setNarrationOpen] = useState(false);
  const [forcedMode, setForcedMode] = useState<NowLineMode | null>(null);

  useEffect(() => {
    setCaptions(readCaptionsEnabled());
    setForcedMode(forcedNowLineMode());
  }, []);

  const matches = playback?.localEpisode && (
    episodeId ? playback.localEpisode.id === episodeId : playback.localEpisode.seed_id === seedId
  );
  const np = matches ? playback : null;
  const episode = np?.localEpisode ?? null;

  const collapse = onCollapse;

  // Narration shown in the NowLine and the full-script sheet. The sheet keeps
  // the last narration so it does not empty out when the host stops talking.
  const narration = np?.current?.kind === "NARRATION" ? np.current : null;
  const narrationText = narration?.narration_text?.trim() || (forcedMode === "narration" ? LAYOUT_SAMPLE : "");
  const sentences = useMemo(() => splitSentences(narrationText), [narrationText]);
  const [sheetNarration, setSheetNarration] = useState<{ id: string; sentences: string[] } | null>(null);
  const narrationId = narration?.id ?? (forcedMode === "narration" ? "layout-sample" : null);
  useEffect(() => {
    if (narrationId && sentences.length) setSheetNarration({ id: narrationId, sentences });
  }, [narrationId, sentences]);

  const music = useMemo(
    () => episode && np ? currentMusicSegment(episode, np.mixPlan, np.browserPosition, np.current) : undefined,
    [episode, np],
  );
  const { ref: coverAreaRef, size: coverSize } = useCoverSize(np?.cover?.titleBelow ? 26 : 0);

  if (!np || !episode) {
    // A start that failed before any episode existed still reports here.
    const sameTarget = Boolean(playback && (
      episodeId ? playback.target.episodeId === episodeId : playback.target.seedId === seedId
    ));
    const failed = Boolean(sameTarget && playback?.error && !playback.localEpisode);
    return (
      <main className="player player-loading" aria-busy={!failed}>
        <div className="player-body">
          <div className="player-top" data-drag-handle>
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
  const darkCover = cover ? isDarkColour(cover.bg) : true;
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
    // Guests: the preference lives on this device only until they sign in.
    if (signedIn) toast.show("会少放这类歌");
    else toast.show("已记下。登录后，这些偏好会一直保存", 3200);
  };

  const toggleCaptions = () => {
    setCaptions((value) => {
      writeCaptionsEnabled(!value);
      return !value;
    });
  };

  // Sentence timing follows the audio position, so seeks re-derive it.
  const sentenceIndexFor = (segmentId: string | null, list: string[]) => {
    if (!list.length) return -1;
    if (!segmentId) return 0;
    const timing = voiceClipTiming(np.mixPlan, segmentId);
    const start = timing?.startSeconds ?? np.mixPlan?.segmentStarts[segmentId] ?? null;
    if (start === null) return 0;
    return currentSentenceIndex(list, np.browserPosition - start, timing?.durationSeconds ?? null);
  };
  const sentenceIndex = sentenceIndexFor(narrationId, sentences);
  const sheetId = sheetNarration?.id ?? null;
  const sheetIndex = sheetId === narrationId
    ? sentenceIndex
    : sentenceIndexFor(sheetId, sheetNarration?.sentences ?? []);

  const mode = forcedMode ?? nowLineMode({ narrating: Boolean(narration), preparing: preparingHint });
  const nextMusic = nextMusicSegment(episode, np.mixPlan, np.browserPosition, music?.id ?? null);
  const nextChapter = chapterNumberOf(episode, nextMusic?.id);
  const next = nextMusic
    ? { primary: trackLabel(nextMusic), secondary: nextChapter ? `第 ${nextChapter} 段` : "" }
    : { primary: `继续收听：${episode.title ?? "WaveCast"}`, secondary: "" };
  const narrationChapter = chapterNumberOf(episode, sheetId);

  return (
    <main className="player" data-cover-tone={darkCover ? "dark" : "light"}>
      {cover ? (
        <div className="player-backdrop" aria-hidden="true">
          <div className="player-backdrop-art">
            <TypeCover params={{ ...cover.params, bare: true }} radius={0} />
          </div>
          <span className="player-backdrop-shade" />
        </div>
      ) : null}

      <div className="player-body">
        {/* The whole 44px top area (not just the grabber) drags the player down. */}
        <div className="player-top-zone" data-drag-handle>
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

        <div ref={coverAreaRef} className="player-cover-area">
          {cover ? (
            <div className="player-cover" data-drag-handle style={{ width: coverSize, height: coverSize }}>
              <TypeCover params={cover.params} radius={12} />
            </div>
          ) : null}
          {cover?.titleBelow ? <p className="player-programme-title" style={{ maxWidth: coverSize }}>{episode.title}</p> : null}
        </div>

        <div className="player-dock">
          <div className="player-meta">
            <div className="player-meta-text">
              <h1>{music?.title || episode.title || "WaveCast"}</h1>
              <p>{music?.artist ?? station?.name ?? ""}</p>
            </div>
            <button type="button" className="glass-icon" aria-label="少放这类" onClick={lessLikeThis}>
              <ThumbDownIcon size={20} strokeWidth={1.8} />
            </button>
          </div>

          <NowLine
            mode={mode}
            sentences={sentences}
            sentenceIndex={Math.max(0, sentenceIndex)}
            captions={captions}
            next={next}
            preparedSeconds={frontier}
            onOpenNarration={() => setNarrationOpen(true)}
            onRetry={!audioReady && np.renderState === "error" ? np.requestProgramRender : undefined}
          />

          <ProgressBar
            position={np.displayedPosition}
            frontier={frontier}
            total={total}
            disabled={!audioReady}
            onPreview={np.updateSeekPreview}
            onCommit={np.commitSeek}
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
      </div>

      {np.error ? <p className="player-error" role="alert">{friendlyError(np.error, "播放遇到了问题，可以稍后重试")}</p> : null}

      {toast.message ? <div className="toast" role="status">{toast.message}</div> : null}

      <RouteSheet
        open={routeOpen}
        onClose={() => setRouteOpen(false)}
        playback={np}
        currentMusicId={music?.id ?? null}
        totalSeconds={total}
      />
      <MoreSheet open={moreOpen} onClose={() => setMoreOpen(false)} playback={np} />
      <NarrationSheet
        open={narrationOpen}
        onClose={() => setNarrationOpen(false)}
        subtitle={narrationChapter ? `第 ${narrationChapter} 段` : episode.title ?? "WaveCast"}
        sentences={sheetNarration?.sentences ?? []}
        index={Math.max(0, sheetIndex)}
      />
    </main>
  );
}
