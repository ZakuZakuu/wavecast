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

  useEffect(() => {
    completedRef.current = false;
  }, [segment?.id]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    const sourceOffsetSeconds = arrangement?.sourceOffsetSeconds ?? 0;
    return attachAudioLifecycle(audio, {
      onTimeUpdate: (sourcePosition) => {
        const position = Math.max(0, sourcePosition - sourceOffsetSeconds);
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
    arrangement?.sourceOffsetSeconds,
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
    const sourceOffsetSeconds = arrangement?.sourceOffsetSeconds ?? 0;
    syncAudioPlayback(audio, {
      sourceUrl: segment?.audio_source_url ?? null,
      positionSeconds: sourceOffsetSeconds + positionSeconds,
      playing,
      syncPosition,
    });
  }, [
    arrangement?.sourceOffsetSeconds,
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

    const applyGain = () => {
      audio.volume = transportSafeGain(arrangement, audio.currentTime);
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
    arrangement?.fadeInSeconds,
    arrangement?.fadeOutSeconds,
    arrangement?.playableDurationSeconds,
    arrangement?.sourceOffsetSeconds,
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
