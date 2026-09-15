"use client";

import { useEffect, useRef } from "react";

import { attachAudioLifecycle, syncAudioPlayback } from "../lib/audio-player";
import type { Segment } from "../lib/types";

export function AudioPlayer({
  segment,
  playing,
  positionSeconds,
  onPositionChange,
  onEnded,
  onError,
}: {
  segment: Segment | undefined;
  playing: boolean;
  positionSeconds: number;
  onPositionChange: (positionSeconds: number) => void;
  onEnded: () => void;
  onError?: () => void;
}) {
  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    return attachAudioLifecycle(audio, {
      onTimeUpdate: onPositionChange,
      onEnded,
      onError,
    });
  }, [onEnded, onError, onPositionChange]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    syncAudioPlayback(audio, {
      sourceUrl: segment?.audio_source_url ?? null,
      positionSeconds,
      playing,
    });
  }, [playing, positionSeconds, segment?.audio_source_url, segment?.id]);

  return <audio ref={audioRef} preload="auto" aria-hidden="true" data-testid="episode-audio" />;
}
