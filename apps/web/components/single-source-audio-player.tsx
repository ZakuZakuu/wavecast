"use client";

import { useEffect, useRef } from "react";

const POSITION_EMIT_INTERVAL_MS = 200;

type SingleSourceAudioPlayerProps = {
  audioUrl: string;
  playing: boolean;
  positionSeconds: number;
  seekToken: number;
  title: string;
  subtitle?: string | null;
  onPositionChange: (positionSeconds: number) => void;
  onPlayRequest: () => void;
  onPauseRequest: () => void;
  onSeekRequest: (positionSeconds: number) => void;
  onBufferingChange?: (buffering: boolean) => void;
  onReady?: () => void;
  onEnded?: () => void;
  onError?: () => void;
};

export function SingleSourceAudioPlayer({
  audioUrl,
  playing,
  positionSeconds,
  seekToken,
  title,
  subtitle,
  onPositionChange,
  onPlayRequest,
  onPauseRequest,
  onSeekRequest,
  onBufferingChange,
  onReady,
  onEnded,
  onError,
}: SingleSourceAudioPlayerProps) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const desiredPositionRef = useRef(positionSeconds);
  const lastSeekTokenRef = useRef(seekToken);
  const lastEmitMsRef = useRef(0);
  const playGenerationRef = useRef(0);

  desiredPositionRef.current = positionSeconds;

  const applyDesiredPosition = () => {
    const audio = audioRef.current;
    if (!audio || audio.readyState === 0) return;
    const desired = Math.max(0, desiredPositionRef.current);
    if (Math.abs(audio.currentTime - desired) > 0.05) {
      try {
        audio.currentTime = desired;
      } catch {
        // Metadata can arrive before the browser exposes a stable seek range.
      }
    }
  };

  const updateMediaSessionPosition = (audio: HTMLAudioElement) => {
    if (typeof navigator === "undefined" || !("mediaSession" in navigator)) return;
    const duration = audio.duration;
    const position = audio.currentTime;
    if (!Number.isFinite(duration) || duration <= 0 || !Number.isFinite(position)) return;
    try {
      navigator.mediaSession.setPositionState({
        duration,
        playbackRate: audio.playbackRate || 1,
        position: Math.min(Math.max(0, position), duration),
      });
    } catch {
      // System media metadata is best effort and must never affect playback.
    }
  };

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    playGenerationRef.current += 1;
    audio.pause();
    audio.src = audioUrl;
    audio.preload = "auto";
    audio.load();
  }, [audioUrl]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    const changed = lastSeekTokenRef.current !== seekToken;
    lastSeekTokenRef.current = seekToken;
    if (changed) applyDesiredPosition();
  }, [seekToken, positionSeconds]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    const generation = playGenerationRef.current + 1;
    playGenerationRef.current = generation;
    if (!playing) {
      audio.pause();
      return;
    }

    void audio.play().catch(() => {
      if (playGenerationRef.current === generation) onError?.();
    });
  }, [playing, audioUrl, onError]);

  useEffect(() => {
    if (typeof navigator === "undefined" || !("mediaSession" in navigator)) return;

    try {
      navigator.mediaSession.metadata = new MediaMetadata({
        title,
        artist: subtitle || "WaveCast",
        album: "WaveCast",
      });
    } catch {
      // Older WebKit builds may expose MediaSession without MediaMetadata.
    }

    const handlers: Array<[MediaSessionAction, MediaSessionActionHandler]> = [
      ["play", () => onPlayRequest()],
      ["pause", () => onPauseRequest()],
      ["stop", () => onPauseRequest()],
      ["seekbackward", (details) => {
        const audio = audioRef.current;
        if (!audio) return;
        onSeekRequest(Math.max(0, audio.currentTime - (details.seekOffset ?? 15)));
      }],
      ["seekforward", (details) => {
        const audio = audioRef.current;
        if (!audio) return;
        onSeekRequest(audio.currentTime + (details.seekOffset ?? 30));
      }],
      ["seekto", (details) => {
        if (typeof details.seekTime === "number") onSeekRequest(details.seekTime);
      }],
    ];

    for (const [action, handler] of handlers) {
      try {
        navigator.mediaSession.setActionHandler(action, handler);
      } catch {
        // Unsupported system actions are optional.
      }
    }
    return () => {
      for (const [action] of handlers) {
        try {
          navigator.mediaSession.setActionHandler(action, null);
        } catch {
          // Ignore unsupported action cleanup.
        }
      }
    };
  }, [onPauseRequest, onPlayRequest, onSeekRequest, subtitle, title]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    const markBuffering = () => onBufferingChange?.(true);
    const markPlaying = () => {
      onBufferingChange?.(false);
      if (typeof navigator !== "undefined" && "mediaSession" in navigator) {
        navigator.mediaSession.playbackState = "playing";
      }
    };
    const markPaused = () => {
      if (typeof navigator !== "undefined" && "mediaSession" in navigator) {
        navigator.mediaSession.playbackState = "paused";
      }
    };
    const metadataReady = () => applyDesiredPosition();
    const ready = () => {
      applyDesiredPosition();
      onReady?.();
    };
    const ended = () => {
      markPaused();
      onEnded?.();
    };
    const failed = () => {
      onBufferingChange?.(false);
      onError?.();
    };

    audio.addEventListener("loadedmetadata", metadataReady);
    audio.addEventListener("canplay", ready);
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
        && now - lastEmitMsRef.current >= POSITION_EMIT_INTERVAL_MS
      ) {
        lastEmitMsRef.current = now;
        onPositionChange(audio.currentTime);
        updateMediaSessionPosition(audio);
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(frame);
      audio.removeEventListener("loadedmetadata", metadataReady);
      audio.removeEventListener("canplay", ready);
      audio.removeEventListener("playing", markPlaying);
      audio.removeEventListener("waiting", markBuffering);
      audio.removeEventListener("stalled", markBuffering);
      audio.removeEventListener("pause", markPaused);
      audio.removeEventListener("ended", ended);
      audio.removeEventListener("error", failed);
    };
  }, [onBufferingChange, onEnded, onError, onPositionChange, onReady]);

  return (
    <audio
      ref={audioRef}
      preload="auto"
      playsInline
      aria-hidden="true"
      data-wavecast-single-source="true"
    />
  );
}
