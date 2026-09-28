"use client";

import { useEffect, useRef } from "react";

import { clampProgramPosition, type ProgramRenderManifest } from "../lib/program-stream";

type ProgrammeAudioPlayerProps = {
  manifest: ProgramRenderManifest;
  playing: boolean;
  positionSeconds: number;
  seekToken: number;
  title: string;
  subtitle?: string | null;
  onPositionChange: (positionSeconds: number) => void;
  onPlayRequest: () => void;
  onPauseRequest: () => void;
  onSeekRequest: (positionSeconds: number) => void;
  onNeedMore: () => void;
  onBufferingChange?: (buffering: boolean) => void;
  onEnded: () => void;
  onError?: () => void;
};

const REFILL_AHEAD_SECONDS = 45;
const POSITION_EMIT_INTERVAL_MS = 200;

export function ProgrammeAudioPlayer({
  manifest,
  playing,
  positionSeconds,
  seekToken,
  title,
  subtitle,
  onPositionChange,
  onPlayRequest,
  onPauseRequest,
  onSeekRequest,
  onNeedMore,
  onBufferingChange,
  onEnded,
  onError,
}: ProgrammeAudioPlayerProps) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const pendingSeekRef = useRef<number | null>(
    clampProgramPosition(manifest, positionSeconds),
  );
  const lastSeekTokenRef = useRef(seekToken);
  const lastEmitMsRef = useRef(0);
  const playGenerationRef = useRef(0);

  const onPositionChangeRef = useRef(onPositionChange);
  const onNeedMoreRef = useRef(onNeedMore);
  const onBufferingChangeRef = useRef(onBufferingChange);
  const onEndedRef = useRef(onEnded);
  const onErrorRef = useRef(onError);
  const onPlayRequestRef = useRef(onPlayRequest);
  const onPauseRequestRef = useRef(onPauseRequest);
  const onSeekRequestRef = useRef(onSeekRequest);

  onPositionChangeRef.current = onPositionChange;
  onNeedMoreRef.current = onNeedMore;
  onBufferingChangeRef.current = onBufferingChange;
  onEndedRef.current = onEnded;
  onErrorRef.current = onError;
  onPlayRequestRef.current = onPlayRequest;
  onPauseRequestRef.current = onPauseRequest;
  onSeekRequestRef.current = onSeekRequest;

  const applyPendingSeek = () => {
    const audio = audioRef.current;
    const pending = pendingSeekRef.current;
    if (!audio || pending === null || audio.readyState === 0) return;

    // Safari can expose HLS metadata before its EVENT playlist has refreshed
    // the full seekable range. Keep one explicit seek pending until that range
    // contains the target; never repeatedly clamp/rewind ordinary playback.
    if (audio.seekable.length > 0) {
      const first = audio.seekable.start(0);
      const last = audio.seekable.end(audio.seekable.length - 1);
      if (pending > last + 0.05) {
        onNeedMoreRef.current();
        return;
      }
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
      onPositionChangeRef.current(desired);
    } catch {
      // canplay/progress/durationchange will retry the same one-shot target.
    }
  };

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    playGenerationRef.current += 1;
    audio.pause();
    pendingSeekRef.current = clampProgramPosition(manifest, positionSeconds);
    audio.src = manifest.streamUrl;
    audio.preload = "auto";
    audio.load();
    applyPendingSeek();
  }, [manifest.episodeId, manifest.streamUrl]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    if (lastSeekTokenRef.current === seekToken) return;

    lastSeekTokenRef.current = seekToken;
    pendingSeekRef.current = clampProgramPosition(manifest, positionSeconds);
    applyPendingSeek();
  }, [manifest, positionSeconds, seekToken]);

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
        // iOS autoplay policy is not a source failure. Keep the same programme
        // element/session and wait for an explicit listener play action.
        onPauseRequestRef.current();
        return;
      }
      onErrorRef.current?.();
    });
  }, [playing, manifest.streamUrl]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    const markBuffering = () => {
      onBufferingChangeRef.current?.(true);
      onNeedMoreRef.current();
    };
    const markPlaying = () => {
      onBufferingChangeRef.current?.(false);
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
    const ended = () => {
      markPaused();
      onEndedRef.current();
    };
    const failed = () => {
      onBufferingChangeRef.current?.(false);
      onErrorRef.current?.();
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
        const position = Math.max(0, audio.currentTime || 0);
        onPositionChangeRef.current(position);
        if (
          !manifest.complete
          && manifest.renderedFrontierSeconds - position <= REFILL_AHEAD_SECONDS
        ) {
          onNeedMoreRef.current();
        }

        if ("mediaSession" in navigator) {
          const duration = audio.duration;
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
      audio.removeEventListener("playing", markPlaying);
      audio.removeEventListener("waiting", markBuffering);
      audio.removeEventListener("stalled", markBuffering);
      audio.removeEventListener("pause", markPaused);
      audio.removeEventListener("ended", ended);
      audio.removeEventListener("error", failed);
    };
  }, [manifest.complete, manifest.renderedFrontierSeconds]);

  useEffect(() => {
    if (!("mediaSession" in navigator)) return;

    try {
      navigator.mediaSession.metadata = new MediaMetadata({
        title,
        artist: subtitle || "WaveCast",
        album: "WaveCast",
      });
    } catch {
      // Older WebKit builds may expose mediaSession without MediaMetadata.
    }

    const seekTo = (position: number) => {
      onSeekRequestRef.current(clampProgramPosition(manifest, position));
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
        navigator.mediaSession.setActionHandler(action, handler);
      } catch {
        // Unsupported system actions are optional.
      }
    }
    navigator.mediaSession.playbackState = playing ? "playing" : "paused";

    return () => {
      for (const [action] of handlers) {
        try {
          navigator.mediaSession.setActionHandler(action, null);
        } catch {
          // Unsupported action cleanup is optional.
        }
      }
    };
  }, [manifest, playing, subtitle, title]);

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
