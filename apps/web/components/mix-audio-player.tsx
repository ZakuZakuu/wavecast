"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { AudioPlayer } from "./audio-player";
import { MixEngine } from "../lib/mix-engine";
import { buildMixPlan } from "../lib/mix-timeline";
import type { LiveEpisode, Segment } from "../lib/types";

export function MixAudioPlayer({
  episode,
  segment,
  playing,
  positionSeconds,
  legacyPositionSeconds,
  onPositionChange,
  onLegacyPositionChange,
  onEnded,
  onError,
}: {
  episode: LiveEpisode;
  segment: Segment | undefined;
  playing: boolean;
  positionSeconds: number;
  legacyPositionSeconds: number;
  onPositionChange: (positionSeconds: number) => void;
  onLegacyPositionChange: (positionSeconds: number) => void;
  onEnded: () => void;
  onError?: () => void;
}) {
  const planKey = episode.segments.map((item) => `${item.id}:${item.state}:${item.audio_source_url}:${item.duration_seconds}`).join("|");
  const plan = useMemo(() => {
    try {
      return buildMixPlan(episode);
    } catch {
      return null;
    }
  }, [episode, planKey]);
  const engineRef = useRef<MixEngine | null>(null);
  const onPositionChangeRef = useRef(onPositionChange);
  const onEndedRef = useRef(onEnded);
  const onErrorRef = useRef(onError);
  const [fallback, setFallback] = useState(false);
  onPositionChangeRef.current = onPositionChange;
  onEndedRef.current = onEnded;
  onErrorRef.current = onError;

  useEffect(() => {
    if (!plan) {
      setFallback(true);
      return undefined;
    }
    try {
      const engine = new MixEngine({
        onPositionChange: (position) => onPositionChangeRef.current(position),
        onEnded: () => onEndedRef.current(),
        onError: () => onErrorRef.current?.(),
      });
      engine.setPlan(plan);
      engineRef.current = engine;
      setFallback(false);
      return () => {
        engine.dispose();
        engineRef.current = null;
      };
    } catch {
      setFallback(true);
      return undefined;
    }
  }, [plan]);

  useEffect(() => {
    engineRef.current?.sync(positionSeconds, playing);
  }, [playing, positionSeconds, plan]);

  if (!plan || fallback) {
    return (
      <AudioPlayer
        segment={segment}
        playing={playing}
        positionSeconds={legacyPositionSeconds}
        onPositionChange={onLegacyPositionChange}
        onEnded={onEnded}
        onError={onError}
      />
    );
  }
  return null;
}
