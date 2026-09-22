"use client";

import { useEffect, useRef, useState } from "react";

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
  const planKey = episode.segments.map((item) => (
    `${item.id}:${item.order}:${item.kind}:${item.audio_source_url ? "ready" : "not-ready"}:${item.audio_source_url}:${item.duration_seconds}`
  )).join("|");
  const planCacheRef = useRef<{ key: string; plan: ReturnType<typeof buildMixPlan> | null }>({
    key: "",
    plan: null,
  });
  if (planCacheRef.current.key !== planKey) {
    let nextPlan: ReturnType<typeof buildMixPlan> | null = null;
    try {
      nextPlan = buildMixPlan(episode);
    } catch {
      nextPlan = null;
    }
    planCacheRef.current = { key: planKey, plan: nextPlan };
  }
  const plan = planCacheRef.current.plan;
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
