"use client";

import { useRef, useState } from "react";

import { clampSeek, formatClock, progressLayers } from "../../lib/now-playing";

/**
 * Three-layer programme progress: played (white), prepared (32% white) and
 * still-preparing (dashed). Dragging cannot pass the prepared frontier; an
 * overshoot springs back and reports `onOvershoot`.
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
  onOvershoot: () => void;
}) {
  const trackRef = useRef<HTMLDivElement | null>(null);
  const [drag, setDrag] = useState<number | null>(null);
  const dragRef = useRef<number | null>(null);

  const shown = drag ?? position;
  const { playedPct, preparedPct } = progressLayers(shown, frontier, total);
  const overshootPct = drag !== null && drag > frontier ? progressLayers(drag, total, total).playedPct : null;

  const valueAt = (clientX: number) => {
    const rect = trackRef.current?.getBoundingClientRect();
    if (!rect || rect.width === 0) return position;
    const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    return ratio * total;
  };

  const update = (value: number) => {
    dragRef.current = value;
    setDrag(value);
    onPreview(clampSeek(value, frontier).position);
  };

  const finish = () => {
    const value = dragRef.current;
    dragRef.current = null;
    setDrag(null);
    if (value === null) return;
    const { position: target, overshoot } = clampSeek(value, frontier);
    if (overshoot) onOvershoot();
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
    if (overshoot) onOvershoot();
    onCommit(target);
  };

  return (
    <div className="progress">
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
          event.currentTarget.setPointerCapture(event.pointerId);
          update(valueAt(event.clientX));
        }}
        onPointerMove={(event) => {
          if (dragRef.current === null) return;
          update(valueAt(event.clientX));
        }}
        onPointerUp={finish}
        onPointerCancel={finish}
        onKeyDown={onKeyDown}
      >
        <div className={drag !== null ? "progress-track dragging" : "progress-track"}>
          <span className="progress-pending" style={{ left: preparedPct + "%" }} />
          <span className="progress-prepared" style={{ width: preparedPct + "%" }} />
          {overshootPct !== null ? <span className="progress-overshoot" style={{ width: overshootPct + "%" }} /> : null}
          <span className="progress-played" style={{ width: playedPct + "%" }} />
        </div>
      </div>
      <div className="progress-times tabular">
        <span>{formatClock(Math.min(shown, frontier))}</span>
        <span>约 {formatClock(total)}</span>
      </div>
    </div>
  );
}
