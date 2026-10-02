"use client";

import { useEffect, useState } from "react";

import { formatFreq, type Station } from "../../lib/stations";
import { waveformPath } from "../../lib/tuner";
import { TuningWindow, useElementWidth } from "./tuning-window";

export type TuningStep = { label: string; done: boolean };

/** Full-screen "开播中": the steps map to real events, never decorative copy. */
export function TuningInScreen({
  station,
  steps,
  error,
  onCancel,
  onRetry,
}: {
  station: Station;
  steps: TuningStep[];
  error: string | null;
  onCancel: () => void;
  onRetry: () => void;
}) {
  const { ref, width } = useElementWidth<HTMLDivElement>();
  const doneCount = steps.filter((step) => step.done).length;
  const progress = doneCount / Math.max(1, steps.length);
  const [seed, setSeed] = useState(42);

  // Re-seed the noise while preparing so the waveform crackles; still when done.
  useEffect(() => {
    if (progress >= 1 || error) return;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    const timer = window.setInterval(() => setSeed((value) => value + 1), 140);
    return () => window.clearInterval(timer);
  }, [error, progress]);

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
            <TuningWindow freq={station.freq} width={width} activeStation={station} pointerGhosts swing />
          </div>
          <div className="tuner-freq tuning-in-freq">
            <span className="tuner-fm">FM</span>
            <span className="tuner-number tabular">{formatFreq(station.freq)}</span>
          </div>
          <span className="tuning-in-name">{station.name}</span>
          <svg className="tuning-in-wave" width="300" height="56" viewBox="0 0 300 56" aria-hidden="true">
            <path d={waveformPath(progress, seed)} style={{ stroke: station.deep }} />
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
            <button type="button" className="pill-button" onClick={onRetry}>重试</button>
          </div>
        ) : null}

        <p className="tuning-in-foot">音乐几秒内就会响起来，<br />后面的内容边播边准备。</p>
      </div>
    </div>
  );
}
