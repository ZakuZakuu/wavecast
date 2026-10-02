"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { STATIONS, type Station } from "../../lib/stations";
import { freqToX, noisePath, tickGeometry } from "../../lib/tuner";

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

/**
 * The inset tuning window: sliding scale, station names above their
 * frequencies, fixed live-orange pointer, edge fades and optional noise.
 */
export function TuningWindow({
  freq,
  width,
  activeStation,
  noise = 0,
  pointerGhosts = false,
  swing = false,
  children,
}: {
  freq: number;
  width: number;
  activeStation: Station | null;
  noise?: number;
  pointerGhosts?: boolean;
  swing?: boolean;
  children?: ReactNode;
}) {
  const ticks = useMemo(() => tickGeometry(freq, width), [freq, width]);
  const noiseD = useMemo(() => noisePath(width), [width]);
  const visible = STATIONS
    .map((station) => ({ station, x: freqToX(station.freq, freq, width) }))
    .filter(({ x }) => x > -40 && x < width + 40);

  return (
    <>
      <svg className="tw-scale" width={width} height={96} viewBox={`0 0 ${width} 96`} aria-hidden="true">
        <path d={ticks.minor} className="tw-minor" />
        <path d={ticks.major} className="tw-major" />
        {noise > 0 ? <path d={noiseD} className="tw-noise" style={{ opacity: noise }} /> : null}
      </svg>
      {visible.map(({ station, x }) => {
        const active = activeStation?.id === station.id;
        const style = { left: x - 40, fontWeight: active ? 600 : 400, color: active ? "var(--ink)" : "var(--ink-3)" };
        const content = (
          <>
            <span className="tw-dot" style={{ background: station.light }} />
            {station.name}
          </>
        );
        return (
          <span key={station.id} className="tw-label" style={style} data-station={station.id} aria-hidden="true">{content}</span>
        );
      })}
      {ticks.numbers.map((number) => (
        <span key={number.label} className="tw-number tabular" style={{ left: number.x - 16 }} aria-hidden="true">
          {number.label}
        </span>
      ))}
      <span className="tw-fade tw-fade-left" aria-hidden="true" />
      <span className="tw-fade tw-fade-right" aria-hidden="true" />
      {pointerGhosts ? (
        <>
          <span className="tw-ghost" style={{ left: width / 2 - 9 }} aria-hidden="true" />
          <span className="tw-ghost" style={{ left: width / 2 + 7 }} aria-hidden="true" />
        </>
      ) : null}
      <span className={swing ? "tw-pointer is-swinging" : "tw-pointer"} style={{ left: width / 2 - 1 }} aria-hidden="true" />
      {children}
    </>
  );
}
