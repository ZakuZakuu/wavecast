"use client";

import { useEffect, useRef } from "react";

import { approach, cleanTarget, swingOffset, waveformPathAt } from "../../lib/motion/ambient";
import { prefersReducedMotion } from "../../lib/motion/easing";
import { useOverlay } from "../../lib/overlay-stack";
import { formatFreq, type Station } from "../../lib/stations";
import { PX_PER_MHZ } from "../../lib/tuner";
import { TuningWindow, useElementWidth } from "./tuning-window";

export type TuningStep = { label: string; done: boolean };

/** Full-screen "开播中": the steps map to real events, never decorative copy. */
export function TuningInScreen({
  station,
  steps,
  error,
  retryable = true,
  onCancel,
  onRetry,
}: {
  station: Station;
  steps: TuningStep[];
  error: string | null;
  /** False for failures that retrying cannot fix; the action then returns to the input. */
  retryable?: boolean;
  onCancel: () => void;
  onRetry: () => void;
}) {
  const { ref, width } = useElementWidth<HTMLDivElement>();
  const doneCount = steps.filter((step) => step.done).length;
  const waveRef = useRef<SVGPathElement | null>(null);
  const targetRef = useRef(cleanTarget(doneCount));
  targetRef.current = cleanTarget(doneCount);

  // One rAF loop on real elapsed time: the pointer's damped swing (first
  // 900ms) and a continuously flowing waveform whose cleanliness eases toward
  // the step target (~6% per frame). No per-frame randomness.
  useEffect(() => {
    const wave = waveRef.current;
    const pointer = ref.current?.querySelector<HTMLElement>(".tw-pointer") ?? null;
    if (prefersReducedMotion()) {
      wave?.setAttribute("d", waveformPathAt(0, 1));
      return;
    }
    const amplitude = 1.2 * PX_PER_MHZ;
    const start = performance.now();
    let last = start;
    let clean = 0;
    let frame = requestAnimationFrame(function tick(now) {
      const elapsed = now - start;
      clean = approach(clean, targetRef.current, now - last);
      last = now;
      if (pointer) {
        const offset = swingOffset(elapsed, amplitude);
        pointer.style.transform = offset ? `translate3d(${offset}px, 0, 0)` : "";
      }
      wave?.setAttribute("d", waveformPathAt(elapsed / 1000, clean));
      frame = requestAnimationFrame(tick);
    });
    return () => cancelAnimationFrame(frame);
  }, [ref]);

  useOverlay(true, onCancel);

  const activeIndex = steps.findIndex((step) => !step.done);

  return (
    <div className="tuning-in" role="dialog" aria-modal="true" aria-label="开播中">
      <span className="glow" aria-hidden="true" style={{ left: -60, top: 80, width: 520, height: 520, background: station.light, opacity: 0.38, filter: "blur(90px)" }} />
      <div className="tuning-in-body">
        <div className="tuning-in-top">
          <button type="button" className="chip-button" onClick={onCancel}>取消</button>
        </div>

        <section className="tuning-in-card" aria-label="正在对准电台">
          <div ref={ref} className="tuning-window is-static" aria-hidden="true">
            <TuningWindow freq={station.freq} width={width} activeStation={station} pointerGhosts />
          </div>
          <div className="tuner-freq tuning-in-freq">
            <span className="tuner-fm">FM</span>
            <span className="tuner-number tabular">{formatFreq(station.freq)}</span>
          </div>
          <span className="tuning-in-name">{station.name}</span>
          <svg className="tuning-in-wave" width="300" height="56" viewBox="0 0 300 56" aria-hidden="true">
            <path ref={waveRef} d={waveformPathAt(0, 0)} style={{ stroke: station.deep }} />
          </svg>
        </section>

        <ol className="tuning-steps" aria-label="准备进度">
          {steps.map((step, index) => (
            <li key={index} className={step.done ? "is-done" : index === activeIndex ? "is-active" : "is-waiting"}>
              <span className="step-mark" aria-hidden="true">
                {step.done ? (
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="m5 12.5 4.5 4.5L19 7" /></svg>
                ) : index === activeIndex && !error ? <span className="step-dot" /> : null}
              </span>
              <span>{step.label}</span>
              <span className="visually-hidden">{step.done ? "（完成）" : ""}</span>
            </li>
          ))}
        </ol>

        {error ? (
          <div className="tuning-error" role="alert">
            <p>{error}</p>
            {retryable ? (
              <button type="button" className="pill-button" onClick={onRetry}>重试</button>
            ) : (
              <button type="button" className="pill-button" onClick={onCancel}>换个说法</button>
            )}
          </div>
        ) : null}

        <p className="tuning-in-foot">音乐几秒内就会响起来，<br />后面的内容边播边准备。</p>
      </div>
    </div>
  );
}
