"use client";

import { useEffect, useRef } from "react";

import {
  attachAudioLifecycle,
  syncAudioPlayback,
  transportSafeGain,
  type TransportSafeArrangement,
} from "../lib/audio-player";
import type { Segment } from "../lib/types";

export function AudioPlayer({
  segment,
  playing,
  positionSeconds,
  seekToken = 0,
  maxDurationSeconds,
  arrangement,
  preloadSourceUrl,
  onPositionChange,
  onEnded,
  onError,
}: {
  segment: Segment | undefined;
  playing: boolean;
  positionSeconds: number;
  seekToken?: number;
  maxDurationSeconds?: number | null;
  arrangement?: TransportSafeArrangement | null;
  preloadSourceUrl?: string | null;
  onPositionChange: (positionSeconds: number) => void;
  onEnded: () => void;
  onError?: () => void;
}) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const lastSeekTokenRef = useRef(seekToken);
  const completedRef = useRef(false);
  const hasArrangement = arrangement !== null && arrangement !== undefined;
  const arrangementSourceOffsetSeconds = arrangement?.sourceOffsetSeconds ?? 0;
  const arrangementPlayableDurationSeconds = arrangement?.playableDurationSeconds ?? 0;
  const arrangementFadeInSeconds = arrangement?.fadeInSeconds ?? 0;
  const arrangementFadeOutSeconds = arrangement?.fadeOutSeconds ?? 0;

  useEffect(() => {
    completedRef.current = false;
  }, [segment?.id]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    return attachAudioLifecycle(audio, {
      onTimeUpdate: (sourcePosition) => {
        const position = Math.max(0, sourcePosition - arrangementSourceOffsetSeconds);
        if (
          maxDurationSeconds !== null
          && maxDurationSeconds !== undefined
          && position >= maxDurationSeconds
        ) {
          if (!completedRef.current) {
            completedRef.current = true;
            audio.pause();
            onPositionChange(maxDurationSeconds);
            onEnded();
          }
          return;
        }
        onPositionChange(position);
      },
      onEnded: () => {
        if (completedRef.current) return;
        completedRef.current = true;
        onEnded();
      },
      onError,
    });
  }, [
    arrangementSourceOffsetSeconds,
    maxDurationSeconds,
    onEnded,
    onError,
    onPositionChange,
  ]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    const syncPosition = lastSeekTokenRef.current !== seekToken;
    lastSeekTokenRef.current = seekToken;
    syncAudioPlayback(audio, {
      sourceUrl: segment?.audio_source_url ?? null,
      positionSeconds: arrangementSourceOffsetSeconds + positionSeconds,
      playing,
      syncPosition,
    });
  }, [
    arrangementSourceOffsetSeconds,
    playing,
    positionSeconds,
    seekToken,
    segment?.audio_source_url,
    segment?.id,
  ]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    let frame: number | null = null;

    const gainArrangement = hasArrangement
      ? {
          sourceOffsetSeconds: arrangementSourceOffsetSeconds,
          playableDurationSeconds: arrangementPlayableDurationSeconds,
          fadeInSeconds: arrangementFadeInSeconds,
          fadeOutSeconds: arrangementFadeOutSeconds,
        }
      : null;

    const applyGain = () => {
      audio.volume = transportSafeGain(gainArrangement, audio.currentTime);
      if (playing) {
        frame = window.requestAnimationFrame(applyGain);
      }
    };

    applyGain();
    return () => {
      if (frame !== null) window.cancelAnimationFrame(frame);
      audio.volume = 1;
    };
  }, [
    arrangementFadeInSeconds,
    arrangementFadeOutSeconds,
    arrangementPlayableDurationSeconds,
    arrangementSourceOffsetSeconds,
    hasArrangement,
    playing,
    segment?.id,
  ]);

  const preload = preloadSourceUrl && preloadSourceUrl !== segment?.audio_source_url
    ? preloadSourceUrl
    : null;

  return (
    <>
      <audio ref={audioRef} preload="auto" aria-hidden="true" data-testid="episode-audio" />
      {preload
        ? (
            <audio
              src={preload}
              preload="auto"
              aria-hidden="true"
              data-testid="episode-audio-preload"
            />
          )
        : null}
    </>
  );
}
