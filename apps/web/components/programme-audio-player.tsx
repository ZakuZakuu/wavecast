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
  onEnded: () => void;
  onError?: () => void;
};

const REFILL_AHEAD_SECONDS = 45;

function safePlay(audio: HTMLAudioElement, onError?: () => void) {
  if (!audio.paused) return;
  void audio.play().catch(() => onError?.());
}

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
  onEnded,
  onError,
}: ProgrammeAudioPlayerProps) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const lastSeekTokenRef = useRef<number>(-1);
  const initialPositionRef = useRef(positionSeconds);
  const onPositionChangeRef = useRef(onPositionChange);
  const onNeedMoreRef = useRef(onNeedMore);
  const onEndedRef = useRef(onEnded);
  const onErrorRef = useRef(onError);
  const onPlayRequestRef = useRef(onPlayRequest);
  const onPauseRequestRef = useRef(onPauseRequest);
  const onSeekRequestRef = useRef(onSeekRequest);

  onPositionChangeRef.current = onPositionChange;
  onNeedMoreRef.current = onNeedMore;
  onEndedRef.current = onEnded;
  onErrorRef.current = onError;
  onPlayRequestRef.current = onPlayRequest;
  onPauseRequestRef.current = onPauseRequest;
  onSeekRequestRef.current = onSeekRequest;

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    const desired = clampProgramPosition(manifest, initialPositionRef.current);
    const align = () => {
      if (Math.abs(audio.currentTime - desired) > 0.05) {
        audio.currentTime = desired;
      }
      onPositionChangeRef.current(desired);
      if (playing) safePlay(audio, onErrorRef.current);
    };
    if (audio.readyState >= 1) {
      align();
      return;
    }
    audio.addEventListener("loadedmetadata", align, { once: true });
    return () => audio.removeEventListener("loadedmetadata", align);
  }, [manifest.episodeId, manifest.streamUrl]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    if (lastSeekTokenRef.current === seekToken) return;
    lastSeekTokenRef.current = seekToken;
    const desired = clampProgramPosition(manifest, positionSeconds);
    if (Math.abs(audio.currentTime - desired) > 0.05) {
      audio.currentTime = desired;
    }
    onPositionChangeRef.current(desired);
  }, [manifest, positionSeconds, seekToken]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    if (playing) {
      safePlay(audio, onErrorRef.current);
    } else {
      audio.pause();
    }
  }, [playing]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    const update = () => {
      const position = Math.max(0, audio.currentTime || 0);
      onPositionChangeRef.current(position);
      if (
        !manifest.complete
        && manifest.renderedFrontierSeconds - position <= REFILL_AHEAD_SECONDS
      ) {
        onNeedMoreRef.current();
      }
      if ("mediaSession" in navigator && manifest.renderedFrontierSeconds > 0) {
        try {
          navigator.mediaSession.setPositionState({
            duration: manifest.renderedFrontierSeconds,
            playbackRate: audio.playbackRate || 1,
            position: Math.min(position, manifest.renderedFrontierSeconds),
          });
        } catch {
          // System media UI is best-effort and must never interrupt playback.
        }
      }
    };
    const waiting = () => onNeedMoreRef.current();
    const ended = () => onEndedRef.current();
    const error = () => onErrorRef.current?.();

    audio.addEventListener("timeupdate", update);
    audio.addEventListener("waiting", waiting);
    audio.addEventListener("stalled", waiting);
    audio.addEventListener("ended", ended);
    audio.addEventListener("error", error);
    return () => {
      audio.removeEventListener("timeupdate", update);
      audio.removeEventListener("waiting", waiting);
      audio.removeEventListener("stalled", waiting);
      audio.removeEventListener("ended", ended);
      audio.removeEventListener("error", error);
    };
  }, [
    manifest.complete,
    manifest.renderedFrontierSeconds,
  ]);

  useEffect(() => {
    if (!("mediaSession" in navigator)) return;

    try {
      navigator.mediaSession.metadata = new MediaMetadata({
        title,
        artist: subtitle || "WaveCast",
        album: "WaveCast",
      });
    } catch {
      // Older Safari variants may expose mediaSession without MediaMetadata.
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
        // Unsupported system action on this browser.
      }
    }
    navigator.mediaSession.playbackState = playing ? "playing" : "paused";

    return () => {
      for (const [action] of handlers) {
        try {
          navigator.mediaSession.setActionHandler(action, null);
        } catch {
          // Unsupported system action on this browser.
        }
      }
    };
  }, [
    manifest,
    playing,
    subtitle,
    title,
  ]);

  return (
    <audio
      ref={audioRef}
      src={manifest.streamUrl}
      preload="auto"
      playsInline
      aria-hidden="true"
      data-testid="programme-audio"
    />
  );
}
