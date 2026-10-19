"use client";

import { useCallback, type MutableRefObject } from "react";

import type { Station } from "../../lib/stations";
import type { TunerReading } from "../../lib/tuner";
import { formatFreq } from "../../lib/stations";
import { ChevronLeftIcon, ChevronRightIcon } from "../icons";
import type { TunerPointerHandlers } from "./use-tuner";
import { TuningWindow, useElementWidth } from "./tuning-window";

/** The dial window: a slider over the scale, with a faint arrow at each end to say it can be dragged. */
export function DialSlider({
  freq,
  reading,
  station,
  dragging,
  wheelRef,
  handlers,
  onKeyDown,
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
        <TuningWindow freq={freq} width={width} activeStation={reading.locked ? station : null} noise={reading.noise}>
          <span className="tw-arrow tw-arrow-left" aria-hidden="true"><ChevronLeftIcon size={16} strokeWidth={2.4} /></span>
          <span className="tw-arrow tw-arrow-right" aria-hidden="true"><ChevronRightIcon size={16} strokeWidth={2.4} /></span>
        </TuningWindow>
      </div>
    </div>
  );
}
