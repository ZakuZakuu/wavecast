"use client";

import { useEffect, useRef } from "react";

const POSITION_EMIT_INTERVAL_MS = 200;

export function supportsNativeHls(): boolean {
  if (typeof document === "undefined") return false;
  const audio = document.createElement("audio");
  return Boolean(
    audio.canPlayType("application/vnd.apple.mpegurl")
    || audio.canPlayType("application/x-mpegURL"),
  );
}

type ProgramStreamPlayerProps = {
  streamUrl: string;
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

export function ProgramStreamPlayer({
  streamUrl,
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
}: ProgramStreamPlayerProps) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const pendingSeekRef = useRef<number | null>(Math.max(0, positionSeconds));
  const lastSeekTokenRef = useRef(seekToken);
  const lastEmitMsRef = useRef(0);
  const playGenerationRef = useRef(0);

  const applyPendingSeek = () => {
    const audio = audioRef.current;
    const pending = pendingSeekRef.current;
    if (!audio || pending === null || audio.readyState === 0) return;

    // Native HLS can expose metadata before Safari has refreshed the EVENT
    // playlist's seekable window. Keep the explicit seek pending rather than
    // clamping it to a stale range or repeatedly rewinding normal playback.
    if (audio.seekable.length > 0) {
      const first = audio.seekable.start(0);
      const last = audio.seekable.end(audio.seekable.length - 1);
      if (pending > last + 0.05) return;
      if (pending < first - 0.05) {
        pendingSeekRef.current = first;
      }
    }

    const desired = Math.max(0, pendingSeekRef.current ?? pending);
    try {
      if (Math.abs(audio.currentTime - desired) > 0.05) {
        audio.currentTime = desired;
      }
      pendingSeekRef.current = null;
    } catch {
      // progress/canplay/durationchange will retry the same explicit target.
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
      // System-media metadata is best effort and must never affect playback.
    }
  };

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    playGenerationRef.current += 1;
    audio.pause();
    pendingSeekRef.current = Math.max(0, positionSeconds);
    audio.src = streamUrl;
    audio.preload = "auto";
    audio.load();
    applyPendingSeek();
  }, [streamUrl]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    const changed = lastSeekTokenRef.current !== seekToken;
    lastSeekTokenRef.current = seekToken;
    if (changed) {
      pendingSeekRef.current = Math.max(0, positionSeconds);
      applyPendingSeek();
    }
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

    void audio.play().catch((reason: unknown) => {
      if (playGenerationRef.current !== generation) return;
      if (reason instanceof DOMException && reason.name === "NotAllowedError") {
        // Autoplay policy is not a transport failure. Leave the programme
        // source intact and wait for the listener's next explicit play action.
        onPauseRequest();
        return;
      }
      onError?.();
    });
  }, [playing, streamUrl, onError, onPauseRequest]);

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

    const handlers: Array<
      [
        MediaSessionAction,
        MediaSessionActionHandler,
      ]
    > = [
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
    const ready = () => {
      applyPendingSeek();
      onReady?.();
    };
    const progress = () => applyPendingSeek();
    const ended = () => {
      markPaused();
      onEnded?.();
    };
    const failed = () => {
      onBufferingChange?.(false);
      onError?.();
    };

    audio.addEventListener("loadedmetadata", ready);
    audio.addEventListener("canplay", ready);
    audio.addEventListener("progress", progress);
    audio.addEventListener("durationchange", progress);
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
      audio.removeEventListener("loadedmetadata", ready);
      audio.removeEventListener("canplay", ready);
      audio.removeEventListener("progress", progress);
      audio.removeEventListener("durationchange", progress);
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
      data-wavecast-program-stream="true"
    />
  );
}
