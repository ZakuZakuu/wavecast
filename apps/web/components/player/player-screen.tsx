"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "../../lib/api";
import { isDarkColour } from "../../lib/cover/build-cover";
import { recordLessLikeThis } from "../../lib/listener-feedback";
import { friendlyError } from "../../lib/friendly-error";
import { chapterNumberOf, currentMusicSegment, estimatedTotalSeconds, nextMusicSegment, publishedNarration, trackLabel, voiceClipTiming } from "../../lib/now-playing";
import { currentSentenceIndex, nowLineMode, splitSentences, type NowLineMode } from "../../lib/now-line";
import { nextJumpStart, previousJumpStart } from "../../lib/playback";
import { coverInFront, rememberCoverChoice, rememberedCoverChoice, songCoverSrc, type CoverFront } from "../../lib/song-cover";
import { formatFreq, stationForProgramme } from "../../lib/stations";
import { TypeCover } from "../cover/type-cover";
import { Back15Icon, ChevronDownIcon, DownloadIcon, Forward15Icon, HeartIcon, MoreIcon, PauseIcon, PlayIcon, PrevIcon, RouteIcon, ScriptIcon, SkipIcon, ThumbDownIcon } from "../icons";
import { ShareSheet } from "../programme/share-sheet";
import { MoreSheet } from "./more-sheet";
import { NarrationSheet, type NarrationPassage } from "./narration-sheet";
import { NowLine } from "./now-line";
import { PlayerCover, useLoadedCover } from "./player-cover";
import { authClient } from "../../lib/auth-client";
import { useNowPlaying, usePlaybackControl, usePlaybackTarget } from "./playback-provider";
import { useFavourite } from "../../lib/use-favourite";
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
  // Most messages sit low, above the controls; confirmations of a tap on the controls sit at the top.
  const [position, setPosition] = useState<"bottom" | "top">("bottom");
  const timer = useRef<number | null>(null);
  const show = useCallback((text: string, durationMs = 2200, where: "bottom" | "top" = "bottom") => {
    setPosition(where);
    setMessage(text);
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setMessage(null), durationMs);
  }, []);
  useEffect(() => () => {
    if (timer.current !== null) window.clearTimeout(timer.current);
  }, []);
  return { message, position, show };
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
  const userId = authClient.useSession().data?.user?.id ?? null;
  const signedIn = userId !== null;
  const { favourite, toggle: toggleFavourite } = useFavourite(playback?.localEpisode?.seed_id ?? seedId ?? null);
  const [routeOpen, setRouteOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);
  const router = useRouter();
  const [narrationOpen, setNarrationOpen] = useState(false);
  const [forcedMode, setForcedMode] = useState<NowLineMode | null>(null);

  useEffect(() => {
    setForcedMode(forcedNowLineMode());
  }, []);

  const matches = playback?.localEpisode && (
    episodeId ? playback.localEpisode.id === episodeId : playback.localEpisode.seed_id === seedId
  );
  const np = matches ? playback : null;
  const episode = np?.localEpisode ?? null;

  const collapse = onCollapse;

  // Narration shown in the NowLine; the script sheet keeps every passage the
  // host has spoken in this programme, so it can be opened whether or not the
  // host is talking right now.
  const narration = np?.current?.kind === "NARRATION" ? np.current : null;
  const narrationText = narration?.narration_text?.trim() || (forcedMode === "narration" ? LAYOUT_SAMPLE : "");
  const sentences = useMemo(() => splitSentences(narrationText), [narrationText]);
  const narrationId = narration?.id ?? (forcedMode === "narration" ? "layout-sample" : null);
  // The script sheet lists what the programme has published of the host's words, not what this
  // screen happened to see being spoken, so it is complete after a resume or a remount.
  const publishedFrontier = np?.maxSeekPosition ?? 0;
  const passageList = useMemo<NarrationPassage[]>(() => {
    if (forcedMode === "narration") return [{ id: "layout-sample", sentences: splitSentences(LAYOUT_SAMPLE) }];
    if (!episode || !np) return [];
    return publishedNarration(episode, np.mixPlan, publishedFrontier).map((item) => ({
      id: item.id,
      sentences: splitSentences(item.text),
    }));
  }, [episode, np, forcedMode, publishedFrontier]);

  const music = useMemo(
    () => episode && np ? currentMusicSegment(episode, np.mixPlan, np.browserPosition, np.current) : undefined,
    [episode, np],
  );
  const { ref: coverAreaRef, size: coverSize } = useCoverSize(np?.cover?.titleBelow ? 26 : 0);
  // The cover of the song under the playhead (during the host's words, the song just before).
  const songCover = useLoadedCover(songCoverSrc(music?.cover_url));
  const [coverChoice, setCoverChoice] = useState<CoverFront | null>(rememberedCoverChoice);

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
  const coverFront = coverInFront({
    choice: coverChoice,
    songReady: songCover.current !== null,
    started: np.browserPlaying || np.browserPosition > 0.5,
  });
  const toggleCover = () => {
    const chosen: CoverFront = coverFront === "song" ? "show" : "song";
    rememberCoverChoice(chosen);
    setCoverChoice(chosen);
  };
  const preparingHint = np.programBuffering || np.preparingAhead || !audioReady;

  const skip = () => {
    const target = np.mixPlan ? nextJumpStart(np.mixPlan, np.browserPosition, episode) : undefined;
    if (target === undefined || target >= frontier) {
      toast.show("后面的内容还在准备");
      return;
    }
    np.nextPlayback();
  };

  const previous = () => {
    if (!np.mixPlan) return;
    np.commitSeek(previousJumpStart(np.mixPlan, np.browserPosition, episode));
  };

  const forward = () => {
    // Only what has been prepared can be played: stop at the prepared edge.
    if (np.browserPosition + 1 >= frontier) {
      toast.show("后面的内容还在准备");
      return;
    }
    np.nudgeSeek(15);
  };

  const lessLikeThis = () => {
    if (music) {
      recordLessLikeThis({ trackRef: music.track_ref, title: music.title, artist: music.artist, episodeId: episode.id });
    }
    const artist = music?.artist?.trim();
    // Guests: the preference lives on this device only until they sign in.
    if (!signedIn) {
      toast.show("已记下。登录后，这些偏好会一直保存", 3200);
      return;
    }
    if (userId && artist) void api.avoidArtist(artist, userId).catch(() => undefined);
    // It steers what is recommended or tuned next; the programme already playing is not redone.
    toast.show(artist ? `已记下，之后的推荐会少放 ${artist}` : "已记下", 3200);
  };

  const prepareFull = () => {
    void np.prepareFullVersion().then((result) => {
      // Started needs no word: the button itself turns to 准备中.
      if (result === "limit") toast.show("最多同时准备 2 档", 2200, "top");
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

  const mode = forcedMode ?? nowLineMode({ narrating: Boolean(narration), preparing: preparingHint });
  const nextMusic = nextMusicSegment(episode, np.mixPlan, np.browserPosition, music?.id ?? null);
  const nextChapter = chapterNumberOf(episode, nextMusic?.id);
  const next = nextMusic
    ? { primary: trackLabel(nextMusic), secondary: nextChapter ? `第 ${nextChapter} 段` : "" }
    : { primary: `继续收听：${episode.title ?? "WaveCast"}`, secondary: "" };

  return (
    <main className="player" data-cover-tone={darkCover ? "dark" : "light"} data-front={songCover.current ? coverFront : undefined}>
      {cover ? (
        <div className="player-backdrop" aria-hidden="true">
          <div className="player-backdrop-art">
            <TypeCover params={{ ...cover.params, bare: true }} radius={0} />
            {songCover.current ? (
              <img className="player-backdrop-song" src={songCover.current} alt="" referrerPolicy="no-referrer" />
            ) : null}
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
            <PlayerCover params={cover.params} size={coverSize} song={songCover} front={coverFront} onToggle={toggleCover} />
          ) : null}
          {cover?.titleBelow ? <p className="player-programme-title" style={{ maxWidth: coverSize }}>{episode.title}</p> : null}
        </div>

        <div className="player-dock">
          <div className="player-meta">
            <div className="player-meta-text">
              <h1>{music?.title || episode.title || "WaveCast"}</h1>
              <p>{music?.artist ?? station?.name ?? ""}</p>
            </div>
            <div className="player-meta-actions">
              <button
                type="button"
                className={`full-pill is-${np.fullVersion}`}
                aria-label={np.fullVersion === "ready" ? "完整版已准备好" : np.fullVersion === "preparing" ? "完整版准备中" : "准备完整版"}
                disabled={np.fullVersion !== "none"}
               
                onClick={prepareFull}
              >
                {np.fullVersion === "none" ? <DownloadIcon size={18} strokeWidth={2} /> : null}
                {np.fullVersion === "preparing" ? <span className="full-pill-ring" aria-hidden="true" /> : null}
                {np.fullVersion === "ready" ? (
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m5 12.5 4.5 4.5L19 7.5" /></svg>
                ) : null}
                {np.fullVersion === "preparing" ? "准备中" : "完整版"}
              </button>
              <button type="button" className="glass-icon" aria-label="少放这类" onClick={lessLikeThis}>
                <ThumbDownIcon size={20} strokeWidth={1.8} />
              </button>
            </div>
          </div>

          <NowLine
            mode={mode}
            sentences={sentences}
            sentenceIndex={Math.max(0, sentenceIndex)}
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
            <button type="button" className="transport-edge" aria-label="上一首" onClick={previous} disabled={!audioReady || !np.mixPlan}>
              <PrevIcon size={26} />
            </button>
            <button type="button" className="transport-side" aria-label="后退 15 秒" onClick={() => np.nudgeSeek(-15)} disabled={!audioReady}>
              <Back15Icon size={32} />
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
            <button type="button" className="transport-side" aria-label="前进 15 秒" onClick={forward} disabled={!audioReady}>
              <Forward15Icon size={32} />
            </button>
            <button type="button" className="transport-edge" aria-label="下一首" onClick={skip} disabled={!audioReady}>
              <SkipIcon size={26} />
            </button>
          </div>

          <div className="player-bottom">
            <button type="button" className="bottom-tool" aria-label="主持词" onClick={() => setNarrationOpen(true)}>
              <ScriptIcon size={22} strokeWidth={1.8} />
            </button>
            <button
              type="button"
              className="bottom-tool"
              aria-label={favourite ? "取消收藏" : "收藏"}
              aria-pressed={favourite}
              onClick={() => toast.show(toggleFavourite() ? "已收藏" : "已取消收藏", 1800, "top")}
            >
              <HeartIcon size={22} strokeWidth={1.8} filled={favourite} />
            </button>
            <button type="button" className="bottom-tool" aria-label="节目路线" onClick={() => setRouteOpen(true)}>
              <RouteIcon size={22} strokeWidth={1.8} />
            </button>
          </div>
        </div>
      </div>

      {np.error ? <p className="player-error" role="alert">{friendlyError(np.error, "播放遇到了问题，可以稍后重试")}</p> : null}

      {toast.message ? <div className={toast.position === "top" ? "toast is-top" : "toast"} role="status">{toast.message}</div> : null}

      <RouteSheet
        open={routeOpen}
        onClose={() => setRouteOpen(false)}
        playback={np}
        currentMusicId={music?.id ?? null}
        totalSeconds={total}
      />
      <MoreSheet
        open={moreOpen}
        onClose={() => setMoreOpen(false)}
        playback={np}
        onDetail={() => router.push(`/program/${encodeURIComponent(episode.seed_id)}`)}
        onShare={() => setShareOpen(true)}
        onPrepareFull={prepareFull}
      />
      <ShareSheet
        open={shareOpen}
        onClose={() => setShareOpen(false)}
        target={{
          id: episode.seed_id,
          title: episode.title ?? "WaveCast",
          coverTitle: episode.cover_title,
          stationId: np.station?.id ?? stationForProgramme(episode.seed_id, episode.title).id,
          episodeId: episode.id,
        }}
      />
      <NarrationSheet
        open={narrationOpen}
        onClose={() => setNarrationOpen(false)}
        subtitle={episode.title ?? "WaveCast"}
        passages={passageList}
        activeId={narration ? narrationId : null}
        activeIndex={Math.max(0, sentenceIndex)}
      />
    </main>
  );
}
