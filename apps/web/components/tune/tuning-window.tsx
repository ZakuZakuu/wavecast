"use client";

import { memo, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { STATIONS, type Station } from "../../lib/stations";
import { FULL_SCALE_WIDTH, fullScaleGeometry, noisePath, scaleTranslate, scaleX } from "../../lib/tuner";

export function useElementWidth<T extends HTMLElement>(fallback = 310) {
  const ref = useRef<T | null>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const element = ref.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      const next = Math.round(entry.contentRect.width);
      if (next > 0) setWidth(next);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return { ref, width };
}

const FULL = fullScaleGeometry();

/**
 * The whole band drawn once. Only its wrapper's translateX changes while
 * tuning (MOTION.md §4.7); labels re-render only when the active station does.
 */
const ScaleContent = memo(function ScaleContent({ activeId }: { activeId: string | null }) {
  return (
    <>
      <svg className="tw-scale" width={FULL_SCALE_WIDTH} height={96} viewBox={`0 0 ${FULL_SCALE_WIDTH} 96`} aria-hidden="true">
        <path d={FULL.minor} className="tw-minor" />
        <path d={FULL.major} className="tw-major" />
      </svg>
      {STATIONS.map((station) => {
        const active = activeId === station.id;
        return (
          <span
            key={station.id}
            className={active ? "tw-label is-active" : "tw-label"}
            style={{ left: scaleX(station.freq) - 40 }}
            data-station={station.id}
            aria-hidden="true"
          >
            <span className="tw-dot" style={{ background: station.light }} />
            {station.name}
          </span>
        );
      })}
      {FULL.numbers.map((number) => (
        <span key={number.label} className="tw-number tabular" style={{ left: number.x - 16 }} aria-hidden="true">
          {number.label}
        </span>
      ))}
    </>
  );
});

/**
 * The inset tuning window: a translateX-only scale layer, fixed live-orange
 * pointer, edge fades and a noise layer whose opacity follows the distance
 * to the nearest station.
 */
export function TuningWindow({
  freq,
  width,
  activeStation,
  noise = 0,
  pointerGhosts = false,
  children,
}: {
  freq: number;
  width: number;
  activeStation: Station | null;
  noise?: number;
  pointerGhosts?: boolean;
  children?: ReactNode;
}) {
  const noiseD = useMemo(() => noisePath(width), [width]);
  return (
    <>
      <div className="tw-layer" style={{ transform: `translate3d(${scaleTranslate(freq, width)}px, 0, 0)` }}>
        <ScaleContent activeId={activeStation?.id ?? null} />
      </div>
      <svg className="tw-noise-layer" width={width} height={96} viewBox={`0 0 ${width} 96`} aria-hidden="true" style={{ opacity: noise }}>
        <path d={noiseD} className="tw-noise" />
      </svg>
      <span className="tw-fade tw-fade-left" aria-hidden="true" />
      <span className="tw-fade tw-fade-right" aria-hidden="true" />
      {pointerGhosts ? (
        <>
          <span className="tw-ghost" style={{ left: width / 2 - 9 }} aria-hidden="true" />
          <span className="tw-ghost" style={{ left: width / 2 + 7 }} aria-hidden="true" />
        </>
      ) : null}
      <span className="tw-pointer" style={{ left: width / 2 - 1 }} aria-hidden="true" />
      {children}
    </>
  );
}
