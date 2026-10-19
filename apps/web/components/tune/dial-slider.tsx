"use client";

import { useCallback, type MutableRefObject } from "react";

import type { Station } from "../../lib/stations";
import type { TunerReading } from "../../lib/tuner";
import { formatFreq } from "../../lib/stations";
import { ChevronLeftIcon, ChevronRightIcon } from "../icons";
import type { TunerPointerHandlers } from "./use-tuner";
import { TuningWindow, useElementWidth } from "./tuning-window";

/**
 * The dial window: a slider over the scale, and at each end a button that steps one station down or up the band
 * (dragging works as before; this is the quick way to the next station).
 */
export function DialSlider({
  freq,
  reading,
  station,
  dragging,
  wheelRef,
  handlers,
  onKeyDown,
  onStep,
  canStep,
  guide,
}: {
  freq: number;
  reading: TunerReading;
  station: Station;
  dragging: boolean;
  /** Receives the window element, for the tuner's wheel handling (only the page's dial wants the wheel). */
  wheelRef?: MutableRefObject<HTMLDivElement | null>;
  handlers: TunerPointerHandlers;
  onKeyDown: (event: React.KeyboardEvent) => void;
  onStep: (direction: 1 | -1) => void;
  /** No station further down (the first one) or up (the last one): that end's button is off. */
  canStep: { down: boolean; up: boolean };
  /** `data-guide` marker for the first-use guide. */
  guide?: string;
}) {
  // The dial measures itself: the guide's card is not on screen until it opens, and it changes size as it grows.
  const { ref: ownRef, width } = useElementWidth<HTMLDivElement>();
  const setRef = useCallback((node: HTMLDivElement | null) => {
    ownRef.current = node;
    if (wheelRef) wheelRef.current = node;
  }, [ownRef, wheelRef]);
  return (
    <div className="tune-dial" data-tuner-dial data-guide={guide}>
      <div
        ref={setRef}
        className={dragging ? "tuning-window is-dragging" : "tuning-window"}
        role="slider"
        tabIndex={0}
        aria-label="调频"
        aria-valuemin={87.5}
        aria-valuemax={108}
        aria-valuenow={Number(formatFreq(freq))}
        aria-valuetext={`FM ${formatFreq(freq)} ${station.name}`}
        onPointerDown={handlers.onPointerDown}
        onPointerMove={handlers.onPointerMove}
        onPointerUp={handlers.onPointerUp}
        onPointerCancel={handlers.onPointerCancel}
        onKeyDown={onKeyDown}
      >
        <TuningWindow freq={freq} width={width} activeStation={reading.locked ? station : null} noise={reading.noise} />
      </div>
      <button type="button" className="tw-step tw-step-down" aria-label="上一个台" disabled={!canStep.down} onClick={() => onStep(-1)}>
        <span><ChevronLeftIcon size={16} strokeWidth={2.4} /></span>
      </button>
      <button type="button" className="tw-step tw-step-up" aria-label="下一个台" disabled={!canStep.up} onClick={() => onStep(1)}>
        <span><ChevronRightIcon size={16} strokeWidth={2.4} /></span>
      </button>
    </div>
  );
}
