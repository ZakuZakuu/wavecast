"use client";

import { useEffect, useRef } from "react";

import {
  evaluateGain,
  type MixClip,
  type MixPlan,
} from "../lib/mix-timeline";
import type { Segment } from "../lib/types";

type DeckKey = "a" | "b";
type DeckSegments = Record<DeckKey, string | null>;

const POSITION_EMIT_INTERVAL_MS = 200;
const DRIFT_CORRECTION_SECONDS = 0.35;
const END_EPSILON_SECONDS = 0.04;

function otherDeck(key: DeckKey): DeckKey {
  return key === "a" ? "b" : "a";
}

function absoluteSourceUrl(sourceUrl: string): string {
  try {
    return new URL(sourceUrl, window.location.href).href;
  } catch {
    return sourceUrl;
  }
}

function clipFor(plan: MixPlan | null, segmentId: string | undefined): MixClip | null {
  if (!plan || !segmentId) return null;
  return plan.clips.find((clip) => clip.segmentId === segmentId) ?? null;
}

function segmentDuration(segment: Segment | undefined): number {
  if (!segment) return 0;
  return segment.duration_seconds
    ?? segment.actual_duration_seconds
    ?? segment.planned_duration_seconds;
}

function safePlay(audio: HTMLAudioElement): void {
  if (!audio.src || !audio.paused) return;
  void audio.play().catch(() => undefined);
}

export function MixAudioPlayer({
  segment,
  upcomingSegment,
  plan,
  playing,
  positionSeconds,
  seekToken = 0,
  armedSuccessorId,
  preloadSourceUrl,
  onPositionChange,
  onEnded,
  onError,
}: {
  segment: Segment | undefined;
  upcomingSegment?: Segment;
  plan: MixPlan | null;
  playing: boolean;
  positionSeconds: number;
  seekToken?: number;
  armedSuccessorId?: string | null;
  preloadSourceUrl?: string | null;
  onPositionChange: (positionSeconds: number) => void;
  onEnded: () => void;
  onError?: () => void;
}) {
  const deckARef = useRef<HTMLAudioElement | null>(null);
  const deckBRef = useRef<HTMLAudioElement | null>(null);
  const deckSegmentsRef = useRef<DeckSegments>({ a: null, b: null });
  const activeDeckRef = useRef<DeckKey>("a");
  const completedRef = useRef(false);
  const lastSeekTokenRef = useRef(seekToken);
  const lastEmitMsRef = useRef(0);
  const onPositionChangeRef = useRef(onPositionChange);
  const onEndedRef = useRef(onEnded);
  const onErrorRef = useRef(onError);

  onPositionChangeRef.current = onPositionChange;
  onEndedRef.current = onEnded;
  onErrorRef.current = onError;

  const currentClip = clipFor(plan, segment?.id);
  const upcomingClip = clipFor(plan, upcomingSegment?.id);
  const currentSourceOffset = currentClip?.sourceOffsetSeconds ?? 0;
  const currentPlayableDuration = currentClip?.playableDurationSeconds
    ?? segmentDuration(segment);

  const deck = (key: DeckKey): HTMLAudioElement | null => (
    key === "a" ? deckARef.current : deckBRef.current
  );

  const configureDeck = (
    key: DeckKey,
    target: Segment,
    sourcePositionSeconds: number,
  ): HTMLAudioElement | null => {
    const audio = deck(key);
    if (!audio || !target.audio_source_url) return null;
    const requested = absoluteSourceUrl(target.audio_source_url);
    if (
      deckSegmentsRef.current[key] !== target.id
      || audio.src !== requested
    ) {
      audio.pause();
      audio.src = requested;
      audio.load();
      audio.currentTime = Math.max(0, sourcePositionSeconds);
      audio.volume = 1;
      deckSegmentsRef.current[key] = target.id;
    }
    return audio;
  };

  useEffect(() => {
    completedRef.current = false;
  }, [segment?.id]);

  useEffect(() => {
    if (!segment?.audio_source_url) {
      deckARef.current?.pause();
      deckBRef.current?.pause();
      return;
    }

    const existing = (["a", "b"] as DeckKey[]).find(
      (key) => deckSegmentsRef.current[key] === segment.id,
    );
    const active = existing ?? activeDeckRef.current;
    activeDeckRef.current = active;
    const currentAudio = configureDeck(
      active,
      segment,
      currentSourceOffset + positionSeconds,
    );
    if (!currentAudio) return;

    const seekChanged = lastSeekTokenRef.current !== seekToken;
    lastSeekTokenRef.current = seekToken;
    if (
      seekChanged
      && Math.abs(
        currentAudio.currentTime - (currentSourceOffset + positionSeconds)
      ) > 0.05
    ) {
      currentAudio.currentTime = Math.max(
        0,
        currentSourceOffset + positionSeconds,
      );
    }

    const secondary = otherDeck(active);
    const preloadTarget = (
      preloadSourceUrl
      && preloadSourceUrl !== segment.audio_source_url
      && (!upcomingSegment?.audio_source_url
        || preloadSourceUrl !== upcomingSegment.audio_source_url)
    )
      ? null
      : upcomingSegment;

    if (preloadTarget?.audio_source_url) {
      configureDeck(
        secondary,
        preloadTarget,
        upcomingClip?.sourceOffsetSeconds ?? 0,
      );
    } else if (preloadSourceUrl && preloadSourceUrl !== segment.audio_source_url) {
      const secondaryAudio = deck(secondary);
      if (secondaryAudio) {
        const requested = absoluteSourceUrl(preloadSourceUrl);
        if (secondaryAudio.src !== requested) {
          secondaryAudio.pause();
          secondaryAudio.src = requested;
          secondaryAudio.load();
          secondaryAudio.currentTime = 0;
          deckSegmentsRef.current[secondary] = null;
        }
      }
    }

    if (playing) {
      safePlay(currentAudio);
    } else {
      deckARef.current?.pause();
      deckBRef.current?.pause();
    }
  }, [
    currentSourceOffset,
    playing,
    positionSeconds,
    preloadSourceUrl,
    seekToken,
    segment?.audio_source_url,
    segment?.id,
    upcomingClip?.sourceOffsetSeconds,
    upcomingSegment?.audio_source_url,
    upcomingSegment?.id,
  ]);

  useEffect(() => {
    const handleEnded = (key: DeckKey) => {
      if (
        key === activeDeckRef.current
        && deckSegmentsRef.current[key] === segment?.id
        && !completedRef.current
      ) {
        completedRef.current = true;
        onEndedRef.current();
      }
    };
    const handleError = (key: DeckKey) => {
      const deckSegmentId = deckSegmentsRef.current[key];
      if (
        deckSegmentId === segment?.id
        || (armedSuccessorId && deckSegmentId === armedSuccessorId)
      ) {
        onErrorRef.current?.();
      }
    };

    const audioA = deckARef.current;
    const audioB = deckBRef.current;
    if (!audioA || !audioB) return undefined;
    const endedA = () => handleEnded("a");
    const endedB = () => handleEnded("b");
    const errorA = () => handleError("a");
    const errorB = () => handleError("b");
    audioA.addEventListener("ended", endedA);
    audioB.addEventListener("ended", endedB);
    audioA.addEventListener("error", errorA);
    audioB.addEventListener("error", errorB);
    return () => {
      audioA.removeEventListener("ended", endedA);
      audioB.removeEventListener("ended", endedB);
      audioA.removeEventListener("error", errorA);
      audioB.removeEventListener("error", errorB);
    };
  }, [armedSuccessorId, segment?.id]);

  useEffect(() => {
    let frame: number | null = null;

    const render = () => {
      const active = activeDeckRef.current;
      const currentAudio = deck(active);
      if (!currentAudio || !segment) return;

      const localPosition = Math.max(
        0,
        currentAudio.currentTime - currentSourceOffset,
      );
      const mixPosition = currentClip
        ? currentClip.timelineStartSeconds + localPosition
        : localPosition;
      const nextIsArmed = Boolean(
        upcomingSegment
        && armedSuccessorId === upcomingSegment.id,
      );
      const nextOverlaps = Boolean(
        currentClip
        && upcomingClip
        && upcomingClip.timelineStartSeconds
          < currentClip.timelineStartSeconds + currentClip.playableDurationSeconds,
      );

      currentAudio.volume = currentClip && (!nextOverlaps || nextIsArmed)
        ? evaluateGain(currentClip, mixPosition)
        : 1;

      const secondary = otherDeck(active);
      const secondaryAudio = deck(secondary);
      if (
        playing
        && currentClip
        && nextIsArmed
        && upcomingSegment?.audio_source_url
        && upcomingClip
        && secondaryAudio
      ) {
        configureDeck(
          secondary,
          upcomingSegment,
          upcomingClip.sourceOffsetSeconds,
        );
        const withinNext = (
          mixPosition >= upcomingClip.timelineStartSeconds
          && mixPosition
            < upcomingClip.timelineStartSeconds
              + upcomingClip.playableDurationSeconds
        );
        if (withinNext) {
          const desiredSourceTime = (
            upcomingClip.sourceOffsetSeconds
            + mixPosition
            - upcomingClip.timelineStartSeconds
          );
          if (
            secondaryAudio.paused
            || Math.abs(secondaryAudio.currentTime - desiredSourceTime)
              > DRIFT_CORRECTION_SECONDS
          ) {
            secondaryAudio.currentTime = Math.max(0, desiredSourceTime);
          }
          secondaryAudio.volume = evaluateGain(upcomingClip, mixPosition);
          safePlay(secondaryAudio);
        } else if (mixPosition < upcomingClip.timelineStartSeconds) {
          secondaryAudio.pause();
          secondaryAudio.volume = 0;
        } else {
          secondaryAudio.pause();
        }
      } else if (
        secondaryAudio
        && deckSegmentsRef.current[secondary] === upcomingSegment?.id
      ) {
        secondaryAudio.pause();
        secondaryAudio.volume = 0;
      }

      const now = performance.now();
      if (now - lastEmitMsRef.current >= POSITION_EMIT_INTERVAL_MS) {
        lastEmitMsRef.current = now;
        onPositionChangeRef.current(localPosition);
      }

      if (
        currentPlayableDuration > 0
        && localPosition >= currentPlayableDuration - END_EPSILON_SECONDS
        && !completedRef.current
      ) {
        completedRef.current = true;
        currentAudio.pause();
        onPositionChangeRef.current(currentPlayableDuration);
        onEndedRef.current();
        return;
      }

      if (playing) {
        frame = window.requestAnimationFrame(render);
      }
    };

    render();
    return () => {
      if (frame !== null) window.cancelAnimationFrame(frame);
    };
  }, [
    armedSuccessorId,
    currentClip,
    currentPlayableDuration,
    currentSourceOffset,
    playing,
    segment,
    upcomingClip,
    upcomingSegment,
  ]);

  return (
    <>
      <audio
        ref={deckARef}
        preload="auto"
        aria-hidden="true"
        data-testid="episode-audio-a"
      />
      <audio
        ref={deckBRef}
        preload="auto"
        aria-hidden="true"
        data-testid="episode-audio-b"
      />
    </>
  );
}
