"use client";

import { useEffect, useRef } from "react";

import type { Segment } from "../lib/types";

const frequencies: Record<string, number> = { MUSIC: 196, NARRATION: 245 };

/** A clearly fake but audible local source, used only until a MusicProvider adapter exists. */
export function TonePlayer({ segment, playing, remainingSeconds, onEnded }: { segment: Segment | undefined; playing: boolean; remainingSeconds: number; onEnded: () => void }) {
  const contextRef = useRef<AudioContext | null>(null);
  const oscillatorRef = useRef<OscillatorNode | null>(null);

  useEffect(() => {
    oscillatorRef.current?.stop();
    oscillatorRef.current = null;
    if (!segment || !playing) return;
    const context = contextRef.current ?? new AudioContext();
    contextRef.current = context;
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.type = segment.kind === "MUSIC" ? "sine" : "triangle";
    oscillator.frequency.value = frequencies[segment.kind];
    gain.gain.value = 0.035;
    oscillator.connect(gain).connect(context.destination);
    void context.resume();
    oscillator.start();
    oscillatorRef.current = oscillator;
    const completion = window.setTimeout(
      onEnded,
      remainingSeconds * 1000,
    );
    return () => { oscillator.stop(); window.clearTimeout(completion); };
  }, [onEnded, playing, remainingSeconds, segment?.id, segment?.kind]);

  return null;
}
