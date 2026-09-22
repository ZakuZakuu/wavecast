"use client";

import { useEffect, useRef, useState } from "react";

import { AudioPlayer } from "./audio-player";
import { MixEngine } from "../lib/mix-engine";
import type { MixPlan } from "../lib/mix-timeline";
import type { Segment } from "../lib/types";

export function MixAudioPlayer({
  segment,
  plan,
  playing,
  positionSeconds,
  legacyPositionSeconds,
  onPositionChange,
  onLegacyPositionChange,
  onEnded,
  onError,
}: {
  segment: Segment | undefined;
  plan: MixPlan | null;
  playing: boolean;
  positionSeconds: number;
  legacyPositionSeconds: number;
  onPositionChange: (positionSeconds: number) => void;
  onLegacyPositionChange: (positionSeconds: number) => void;
  onEnded: () => void;
  onError?: () => void;
}) {
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
