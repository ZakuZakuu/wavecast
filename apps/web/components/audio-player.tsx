"use client";

import { useEffect, useRef } from "react";

import { attachAudioLifecycle, syncAudioPlayback } from "../lib/audio-player";
import type { Segment } from "../lib/types";

export function AudioPlayer({
  segment,
  playing,
  positionSeconds,
  seekToken = 0,
  maxDurationSeconds,
  onPositionChange,
  onEnded,
  onError,
}: {
  segment: Segment | undefined;
  playing: boolean;
  positionSeconds: number;
  seekToken?: number;
  maxDurationSeconds?: number | null;
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
    return attachAudioLifecycle(audio, {
      onTimeUpdate: (position) => {
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
  }, [maxDurationSeconds, onEnded, onError, onPositionChange]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    const syncPosition = lastSeekTokenRef.current !== seekToken;
    lastSeekTokenRef.current = seekToken;
    syncAudioPlayback(audio, {
      sourceUrl: segment?.audio_source_url ?? null,
      positionSeconds,
      playing,
      syncPosition,
    });
  }, [playing, positionSeconds, seekToken, segment?.audio_source_url, segment?.id]);

  return <audio ref={audioRef} preload="auto" aria-hidden="true" data-testid="episode-audio" />;
}
