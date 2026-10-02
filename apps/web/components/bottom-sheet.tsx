"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

import { Portal } from "./portal";

const CLOSE_DISTANCE = 96;

/**
 * Frosted bottom sheet: slides up, closes on backdrop tap, Escape, or a
 * downward drag past the threshold (otherwise it springs back).
 */
export function BottomSheet({
  open,
  onClose,
  label,
  tone = "light",
  height,
  children,
  className,
}: {
  open: boolean;
  onClose: () => void;
  label: string;
  tone?: "light" | "dark";
  height?: string;
  children: ReactNode;
  className?: string;
}) {
  const [drag, setDrag] = useState(0);
  const startRef = useRef<number | null>(null);
  const panelRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    panelRef.current?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, open]);

  useEffect(() => {
    if (!open) setDrag(0);
  }, [open]);

  if (!open) return null;

  const onPointerDown = (event: React.PointerEvent) => {
    startRef.current = event.clientY;
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
  };
  const onPointerMove = (event: React.PointerEvent) => {
    if (startRef.current === null) return;
    setDrag(Math.max(0, event.clientY - startRef.current));
  };
  const onPointerUp = () => {
    if (startRef.current === null) return;
    startRef.current = null;
    if (drag > CLOSE_DISTANCE) onClose();
    else setDrag(0);
  };

  return (
    <Portal>
    <div className="sheet-layer" role="presentation">
      <div className="sheet-scrim" onClick={onClose} aria-hidden="true" />
      <section
        ref={panelRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={label}
        className={`sheet sheet-${tone}${className ? " " + className : ""}`}
        style={{
          height,
          transform: drag ? `translateY(${drag}px)` : undefined,
          transition: startRef.current === null ? undefined : "none",
        }}
      >
        <div
          className="sheet-handle-zone"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
        >
          <span className="sheet-handle" aria-hidden="true" />
        </div>
        {children}
      </section>
    </div>
    </Portal>
  );
}
