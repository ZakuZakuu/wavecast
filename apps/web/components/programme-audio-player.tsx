"use client";

import { useCallback, useEffect, useRef } from "react";

const HLS_MIME = "application/vnd.apple.mpegurl";
const FRONTIER_WAKE_SECONDS = 12;
const FRONTIER_SEEK_EPSILON_SECONDS = 0.05;
const POSITION_EMIT_INTERVAL_MS = 200;

type ProgrammeAudioPlayerProps = {
  streamUrl: string;
  playing: boolean;
  positionSeconds: number;
  seekToken: number;
  renderedFrontierSeconds: number;
  complete: boolean;
  title: string;
  artist?: string | null;
  onPositionChange: (positionSeconds: number) => void;
  onPlayingChange?: (playing: boolean) => void;
  onBufferingChange?: (buffering: boolean) => void;
  onEnded: () => void;
  onFrontierReached: () => void;
  onPlayRequest: () => void;
  onPauseRequest: () => void;
  onSeekRequest: (positionSeconds: number) => void;
  onError: (message: string) => void;
};

export function ProgrammeAudioPlayer({
  streamUrl,
  playing,
  positionSeconds,
  seekToken,
  renderedFrontierSeconds,
  complete,
  title,
  artist,
  onPositionChange,
  onPlayingChange,
  onBufferingChange,
  onEnded,
  onFrontierReached,
  onPlayRequest,
  onPauseRequest,
  onSeekRequest,
  onError,
}: ProgrammeAudioPlayerProps) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const hlsRef = useRef<import("hls.js").default | null>(null);
  const pendingSeekRef = useRef<number | null>(Math.max(0, positionSeconds));
  const desiredPlayingRef = useRef(playing);
  const frontierRef = useRef(renderedFrontierSeconds);
  const completeRef = useRef(complete);
  const lastSeekTokenRef = useRef(seekToken);
  const lastEmitMsRef = useRef(0);
  const appliedSeekTargetRef = useRef<number | null>(null);
  const playGenerationRef = useRef(0);

  const onPositionChangeRef = useRef(onPositionChange);
  const onPlayingChangeRef = useRef(onPlayingChange);
  const onBufferingChangeRef = useRef(onBufferingChange);
  const onEndedRef = useRef(onEnded);
  const onFrontierReachedRef = useRef(onFrontierReached);
  const onPlayRequestRef = useRef(onPlayRequest);
  const onPauseRequestRef = useRef(onPauseRequest);
  const onSeekRequestRef = useRef(onSeekRequest);
  const onErrorRef = useRef(onError);

  desiredPlayingRef.current = playing;
  frontierRef.current = renderedFrontierSeconds;
  completeRef.current = complete;
  onPositionChangeRef.current = onPositionChange;
  onPlayingChangeRef.current = onPlayingChange;
  onBufferingChangeRef.current = onBufferingChange;
  onEndedRef.current = onEnded;
  onFrontierReachedRef.current = onFrontierReached;
  onPlayRequestRef.current = onPlayRequest;
  onPauseRequestRef.current = onPauseRequest;
  onSeekRequestRef.current = onSeekRequest;
  onErrorRef.current = onError;

  const applyPendingSeek = useCallback(() => {
    const audio = audioRef.current;
    const pending = pendingSeekRef.current;
    if (!audio || pending === null || audio.readyState === 0) return;

    let target = Math.max(0, pending);
    const frontier = Math.max(0, frontierRef.current);

    if (
      !completeRef.current
      && target > Math.max(0, frontier - FRONTIER_SEEK_EPSILON_SECONDS)
    ) {
      onFrontierReachedRef.current();
      return;
    }
    if (completeRef.current) {
      target = Math.min(target, frontier);
    }

    if (audio.seekable.length > 0) {
      const first = audio.seekable.start(0);
      const last = audio.seekable.end(audio.seekable.length - 1);
      if (target > last + FRONTIER_SEEK_EPSILON_SECONDS) {
        onFrontierReachedRef.current();
        return;
      }
      if (target < first - FRONTIER_SEEK_EPSILON_SECONDS) {
        return;
      }
    }

    // MSE/hls.js can apply currentTime asynchronously. Keep the seek intent
    // pending until the media element confirms the target instead of allowing
    // one stale frame to overwrite the requested position.
    if (
      Math.abs(audio.currentTime - target) <= FRONTIER_SEEK_EPSILON_SECONDS
      && !audio.seeking
    ) {
      pendingSeekRef.current = null;
      appliedSeekTargetRef.current = null;
      onPositionChangeRef.current(target);
      return;
    }

    if (
      !audio.seeking
      && (
        appliedSeekTargetRef.current === null
        || Math.abs(appliedSeekTargetRef.current - target)
          > FRONTIER_SEEK_EPSILON_SECONDS
      )
    ) {
      try {
        appliedSeekTargetRef.current = target;
        audio.currentTime = target;
      } catch {
        appliedSeekTargetRef.current = null;
      }
    }
  }, []);

  const playIfDesired = useCallback(() => {
    const audio = audioRef.current;
    if (
      !audio
      || !desiredPlayingRef.current
      || !audio.paused
      || pendingSeekRef.current !== null
    ) return;

    const generation = playGenerationRef.current + 1;
    playGenerationRef.current = generation;
    void audio.play().catch((reason: unknown) => {
      if (playGenerationRef.current !== generation) return;
      if (reason instanceof DOMException && reason.name === "NotAllowedError") {
        // iOS autoplay policy is a normal paused state, not a broken source.
        onPauseRequestRef.current();
        return;
      }
      onErrorRef.current("节目音频暂时无法播放");
    });
  }, []);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio || !streamUrl) return;

    let cancelled = false;
    let detachNativeListeners: (() => void) | null = null;
    let networkRecoveryUsed = false;
    let mediaRecoveryUsed = false;

    playGenerationRef.current += 1;
    audio.pause();
    pendingSeekRef.current = Math.max(0, positionSeconds);
    appliedSeekTargetRef.current = null;
    onBufferingChangeRef.current?.(true);

    const wakeIfDesired = () => {
      if (cancelled) return;
      applyPendingSeek();
      playIfDesired();
    };

    const attachNative = () => {
      audio.src = streamUrl;
      audio.preload = "auto";
      const events = ["loadedmetadata", "durationchange", "canplay", "progress"];
      for (const event of events) audio.addEventListener(event, wakeIfDesired);
      detachNativeListeners = () => {
        for (const event of events) {
          audio.removeEventListener(event, wakeIfDesired);
        }
      };
      audio.load();
      wakeIfDesired();
    };

    if (audio.canPlayType(HLS_MIME)) {
      attachNative();
    } else {
      void import("hls.js")
        .then(({ default: Hls }) => {
          if (cancelled) return;
          if (!Hls.isSupported()) {
            onErrorRef.current("当前浏览器暂时不支持节目流播放");
            return;
          }

          const hls = new Hls({
            enableWorker: true,
            lowLatencyMode: false,
            backBufferLength: 600,
            maxBufferLength: 120,
            startPosition: Math.max(0, positionSeconds),
          });
          hlsRef.current = hls;
          hls.attachMedia(audio);
          hls.on(Hls.Events.MEDIA_ATTACHED, () => {
            if (!cancelled) hls.loadSource(streamUrl);
          });
          hls.on(Hls.Events.MANIFEST_PARSED, wakeIfDesired);
          hls.on(Hls.Events.LEVEL_UPDATED, wakeIfDesired);
          hls.on(Hls.Events.ERROR, (_event, data) => {
            if (cancelled || !data.fatal) return;
            if (
              data.type === Hls.ErrorTypes.NETWORK_ERROR
              && !networkRecoveryUsed
            ) {
              networkRecoveryUsed = true;
              hls.startLoad();
              return;
            }
            if (
              data.type === Hls.ErrorTypes.MEDIA_ERROR
              && !mediaRecoveryUsed
            ) {
              mediaRecoveryUsed = true;
              hls.recoverMediaError();
              return;
            }
            onErrorRef.current("节目流暂时无法继续播放");
          });
        })
        .catch(() => {
          if (!cancelled) onErrorRef.current("节目播放器加载失败");
        });
    }

    return () => {
      cancelled = true;
      detachNativeListeners?.();
      hlsRef.current?.destroy();
      hlsRef.current = null;
      playGenerationRef.current += 1;
      audio.pause();
      audio.removeAttribute("src");
      audio.load();
    };
    // streamUrl is the source identity. Callback props deliberately live in
    // refs so progress renders never tear down the persistent HLS session.
  }, [applyPendingSeek, playIfDesired, streamUrl]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    if (lastSeekTokenRef.current === seekToken) return;

    lastSeekTokenRef.current = seekToken;
    pendingSeekRef.current = Math.max(0, positionSeconds);
    appliedSeekTargetRef.current = null;
    applyPendingSeek();
  }, [applyPendingSeek, positionSeconds, seekToken]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    playGenerationRef.current += 1;
    if (playing) {
      playIfDesired();
    } else {
      audio.pause();
    }
    if ("mediaSession" in navigator) {
      navigator.mediaSession.playbackState = playing ? "playing" : "paused";
    }
  }, [playIfDesired, playing]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    const markBuffering = () => {
      onBufferingChangeRef.current?.(true);
      onFrontierReachedRef.current();
    };
    const markPlaying = () => {
      onBufferingChangeRef.current?.(false);
      onPlayingChangeRef.current?.(true);
      if ("mediaSession" in navigator) {
        navigator.mediaSession.playbackState = "playing";
      }
    };
    const markPaused = () => {
      if ("mediaSession" in navigator) {
        navigator.mediaSession.playbackState = "paused";
      }
    };
    const ready = () => {
      applyPendingSeek();
      onBufferingChangeRef.current?.(false);
    };
    const progress = () => applyPendingSeek();
    const seeked = () => {
      const pending = pendingSeekRef.current;
      if (pending !== null && appliedSeekTargetRef.current !== null) {
        // The media element owns the final seek landing point. MSE/hls.js may
        // resolve to a nearby decoded timestamp instead of the exact requested
        // float, so a real seeked event is the completion signal.
        const actual = Math.max(0, audio.currentTime || 0);
        pendingSeekRef.current = null;
        appliedSeekTargetRef.current = null;
        onPositionChangeRef.current(actual);
        onBufferingChangeRef.current?.(false);
      } else {
        applyPendingSeek();
      }
      playIfDesired();
    };
    const ended = () => {
      markPaused();
      if (completeRef.current) {
        onEndedRef.current();
      } else {
        onFrontierReachedRef.current();
      }
    };
    const failed = () => {
      onBufferingChangeRef.current?.(false);
      onErrorRef.current("节目音频暂时无法播放");
    };

    audio.addEventListener("loadedmetadata", ready);
    audio.addEventListener("canplay", ready);
    audio.addEventListener("progress", progress);
    audio.addEventListener("durationchange", progress);
    audio.addEventListener("seeked", seeked);
    audio.addEventListener("playing", markPlaying);
    audio.addEventListener("waiting", markBuffering);
    audio.addEventListener("stalled", markBuffering);
    audio.addEventListener("pause", markPaused);
    audio.addEventListener("ended", ended);
    audio.addEventListener("error", failed);

    let frame = 0;
    const tick = (now: number) => {
      if (
        !audio.paused
        && pendingSeekRef.current === null
        && now - lastEmitMsRef.current >= POSITION_EMIT_INTERVAL_MS
      ) {
        lastEmitMsRef.current = now;
        const position = Math.max(0, audio.currentTime || 0);
        onPositionChangeRef.current(position);

        if (
          !completeRef.current
          && frontierRef.current - position <= FRONTIER_WAKE_SECONDS
        ) {
          onFrontierReachedRef.current();
        }

        if ("mediaSession" in navigator) {
          const duration = frontierRef.current;
          if (
            Number.isFinite(duration)
            && duration > 0
            && Number.isFinite(position)
          ) {
            try {
              navigator.mediaSession.setPositionState({
                duration,
                playbackRate: audio.playbackRate || 1,
                position: Math.min(position, duration),
              });
            } catch {
              // System media state is best-effort.
            }
          }
        }
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(frame);
      audio.removeEventListener("loadedmetadata", ready);
      audio.removeEventListener("canplay", ready);
      audio.removeEventListener("progress", progress);
      audio.removeEventListener("durationchange", progress);
      audio.removeEventListener("seeked", seeked);
      audio.removeEventListener("playing", markPlaying);
      audio.removeEventListener("waiting", markBuffering);
      audio.removeEventListener("stalled", markBuffering);
      audio.removeEventListener("pause", markPaused);
      audio.removeEventListener("ended", ended);
      audio.removeEventListener("error", failed);
    };
  }, [applyPendingSeek, playIfDesired]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    const syncVisiblePosition = () => {
      if (
        document.visibilityState === "visible"
        && pendingSeekRef.current === null
        && audio.readyState > 0
      ) {
        onPositionChangeRef.current(Math.max(0, audio.currentTime || 0));
      }
    };

    document.addEventListener("visibilitychange", syncVisiblePosition);
    window.addEventListener("pageshow", syncVisiblePosition);
    return () => {
      document.removeEventListener("visibilitychange", syncVisiblePosition);
      window.removeEventListener("pageshow", syncVisiblePosition);
    };
  }, []);

  useEffect(() => {
    if (!("mediaSession" in navigator)) return;

    try {
      navigator.mediaSession.metadata = new MediaMetadata({
        title,
        artist: artist || "WaveCast",
        album: "WaveCast",
      });
    } catch {
      // Older WebKit builds may expose mediaSession without MediaMetadata.
    }
  }, [artist, title]);

  useEffect(() => {
    if (!("mediaSession" in navigator)) return;
    const mediaSession = navigator.mediaSession;
    const seekTo = (position: number) => {
      onSeekRequestRef.current(
        Math.max(0, Math.min(frontierRef.current, position)),
      );
    };
    const handlers: Array<
      [
        MediaSessionAction,
        ((details: MediaSessionActionDetails) => void) | null,
      ]
    > = [
      ["play", () => onPlayRequestRef.current()],
      ["pause", () => onPauseRequestRef.current()],
      ["stop", () => onPauseRequestRef.current()],
      ["seekbackward", (details) => {
        const audio = audioRef.current;
        if (!audio) return;
        seekTo(audio.currentTime - (details.seekOffset ?? 15));
      }],
      ["seekforward", (details) => {
        const audio = audioRef.current;
        if (!audio) return;
        seekTo(audio.currentTime + (details.seekOffset ?? 30));
      }],
      ["seekto", (details) => {
        if (typeof details.seekTime === "number") seekTo(details.seekTime);
      }],
    ];

    for (const [action, handler] of handlers) {
      try {
        mediaSession.setActionHandler(action, handler);
      } catch {
        // Unsupported system actions are optional.
      }
    }

    return () => {
      for (const [action] of handlers) {
        try {
          mediaSession.setActionHandler(action, null);
        } catch {
          // Unsupported action cleanup is optional.
        }
      }
    };
  }, []);

  return (
    <audio
      ref={audioRef}
      preload="auto"
      playsInline
      aria-hidden="true"
      data-testid="programme-audio"
    />
  );
}
