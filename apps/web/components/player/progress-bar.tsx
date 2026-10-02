"use client";

import { useEffect, useRef, useState } from "react";

import { prefersReducedMotion } from "../../lib/motion/easing";
import { rubberBand } from "../../lib/motion/gesture";
import { animateSpring, type Cancel } from "../../lib/motion/spring";
import { clampSeek, formatClock, progressLayers } from "../../lib/now-playing";

/** Overshoot past the prepared point is damped to "just a little". */
const OVERSHOOT_LIMIT_PX = 24;
const HINT_MS = 1500;

/**
 * Three-layer programme progress: played (white), prepared (32% white) and
 * still-preparing (dashed). Fills use transform: scaleX (no width animation).
 * Dragging past the prepared point stretches a little (rubber band), springs
 * back on release and shows 这部分还在准备 above the bar for 1.5s.
 */
export function ProgressBar({
  position,
  frontier,
  total,
  disabled,
  onPreview,
  onCommit,
  onOvershoot,
}: {
  position: number;
  frontier: number;
  total: number;
  disabled?: boolean;
  onPreview: (seconds: number) => void;
  onCommit: (seconds: number) => void;
  onOvershoot?: () => void;
}) {
  const trackRef = useRef<HTMLDivElement | null>(null);
  const [drag, setDrag] = useState<number | null>(null);
  const dragRef = useRef<number | null>(null);
  // Extra px shown past the prepared point (rubber band, then spring back).
  const [overshootPx, setOvershootPx] = useState(0);
  const springRef = useRef<Cancel | null>(null);
  const [hint, setHint] = useState(false);
  const hintTimer = useRef<number | null>(null);

  useEffect(() => () => {
    springRef.current?.();
    if (hintTimer.current !== null) window.clearTimeout(hintTimer.current);
  }, []);

  const trackWidth = () => trackRef.current?.getBoundingClientRect().width ?? 0;
  const shown = drag !== null ? Math.min(drag, frontier) : position;
  const { playedPct, preparedPct } = progressLayers(shown, frontier, total);
  const width = trackWidth() || 1;
  const overshootPct = (overshootPx / width) * 100;
  const playedScale = Math.min(100, playedPct + (shown >= frontier - 0.01 ? overshootPct : 0)) / 100;

  const valueAt = (clientX: number) => {
    const rect = trackRef.current?.getBoundingClientRect();
    if (!rect || rect.width === 0) return { seconds: position, beyondPx: 0 };
    const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    const seconds = ratio * total;
    const frontierPx = (frontier / Math.max(1, total)) * rect.width;
    const beyondPx = Math.max(0, clientX - rect.left - frontierPx);
    return { seconds, beyondPx };
  };

  const showHint = () => {
    setHint(true);
    if (hintTimer.current !== null) window.clearTimeout(hintTimer.current);
    hintTimer.current = window.setTimeout(() => setHint(false), HINT_MS);
    onOvershoot?.();
  };

  const update = (clientX: number) => {
    const { seconds, beyondPx } = valueAt(clientX);
    dragRef.current = seconds;
    setDrag(seconds);
    setOvershootPx(beyondPx > 0 ? rubberBand(beyondPx, OVERSHOOT_LIMIT_PX) : 0);
    onPreview(clampSeek(seconds, frontier).position);
  };

  const springBack = () => {
    springRef.current?.();
    if (prefersReducedMotion()) {
      setOvershootPx(0);
      return;
    }
    springRef.current = animateSpring({ from: overshootPx, to: 0, epsilon: 0.3, onUpdate: setOvershootPx });
  };

  const finish = () => {
    const value = dragRef.current;
    dragRef.current = null;
    setDrag(null);
    if (value === null) return;
    const { position: target, overshoot } = clampSeek(value, frontier);
    if (overshoot) {
      showHint();
      springBack();
    } else {
      setOvershootPx(0);
    }
    onCommit(target);
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    const step = event.shiftKey ? 30 : 5;
    let next: number | null = null;
    if (event.key === "ArrowRight" || event.key === "ArrowUp") next = position + step;
    if (event.key === "ArrowLeft" || event.key === "ArrowDown") next = position - step;
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = frontier;
    if (next === null) return;
    event.preventDefault();
    const { position: target, overshoot } = clampSeek(next, frontier);
    if (overshoot) showHint();
    onCommit(target);
  };

  return (
    <div className="progress">
      <span className={hint ? "progress-hint is-visible" : "progress-hint"} aria-live="polite">
        {hint ? "这部分还在准备" : ""}
      </span>
      <div
        ref={trackRef}
        className="progress-hit"
        role="slider"
        tabIndex={disabled ? -1 : 0}
        aria-label="节目进度"
        aria-valuemin={0}
        aria-valuemax={Math.round(total)}
        aria-valuenow={Math.round(Math.min(shown, frontier))}
        aria-valuetext={`已播 ${formatClock(shown)}，已准备到 ${formatClock(frontier)}，全长约 ${formatClock(total)}`}
        aria-disabled={disabled || undefined}
        onPointerDown={(event) => {
          if (disabled) return;
          springRef.current?.();
          event.currentTarget.setPointerCapture(event.pointerId);
          update(event.clientX);
        }}
        onPointerMove={(event) => {
          if (dragRef.current === null) return;
          update(event.clientX);
        }}
        onPointerUp={finish}
        onPointerCancel={finish}
        onKeyDown={onKeyDown}
      >
        <div className={drag !== null ? "progress-track dragging" : "progress-track"}>
          <span className="progress-pending" style={{ left: preparedPct + "%" }} />
          <span className="progress-prepared" style={{ transform: `scaleX(${preparedPct / 100})` }} />
          <span className="progress-played" style={{ transform: `scaleX(${playedScale})` }} />
        </div>
      </div>
      <div className="progress-times tabular">
        <span>{formatClock(Math.min(shown, frontier))}</span>
        <span>约 {formatClock(total)}</span>
      </div>
    </div>
  );
}
