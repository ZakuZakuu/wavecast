"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import { DUR, easeExit, prefersReducedMotion, tween } from "../../lib/motion/easing";
import { VelocityTracker } from "../../lib/motion/gesture";
import { animateSpring, type Cancel } from "../../lib/motion/spring";

const REVEAL = 84;
const OPEN_THRESHOLD = 40;
const DELETE_RATIO = 0.6;
const LOCK_DISTANCE = 6;

/** Where a released swipe should settle (MOTION.md §4.10). */
export function swipeDecision(offset: number, rowWidth: number, velocity: number): "delete" | "open" | "close" {
  const revealed = -offset;
  if (rowWidth > 0 && revealed > rowWidth * DELETE_RATIO) return "delete";
  if (velocity < -0.5) return "open";
  if (velocity > 0.5) return "close";
  return revealed > OPEN_THRESHOLD ? "open" : "close";
}

/**
 * Library row with swipe-to-delete: follows the finger, springs to reveal
 * the 84px 删除 past 40px, deletes outright past 60% of the row (slides out,
 * then the row height collapses). Only one row is open at a time.
 */
export function SwipeRow({
  children,
  onDelete,
  deleteLabel,
  open,
  onOpenChange,
  rowKey,
}: {
  rowKey: string;
  children: ReactNode;
  onDelete?: () => void;
  deleteLabel: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const rowRef = useRef<HTMLLIElement | null>(null);
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const offsetRef = useRef(0);
  const cancelRef = useRef<Cancel | null>(null);
  const gesture = useRef<{ x: number; y: number; base: number; locked: "x" | "y" | null; tracker: VelocityTracker } | null>(null);
  const movedRef = useRef(false);
  const [removing, setRemoving] = useState(false);

  const apply = useCallback((offset: number) => {
    offsetRef.current = offset;
    if (bodyRef.current) bodyRef.current.style.transform = offset ? `translate3d(${offset}px, 0, 0)` : "";
  }, []);

  const settle = useCallback((target: number, velocity = 0) => {
    cancelRef.current?.();
    if (prefersReducedMotion()) {
      apply(target);
      return;
    }
    cancelRef.current = animateSpring({ from: offsetRef.current, to: target, velocity, onUpdate: apply });
  }, [apply]);

  const remove = useCallback(() => {
    if (!onDelete || removing) return;
    cancelRef.current?.();
    const width = rowRef.current?.offsetWidth ?? 360;
    const collapse = () => setRemoving(true);
    if (prefersReducedMotion()) {
      collapse();
      return;
    }
    cancelRef.current = tween({ from: offsetRef.current, to: -width, duration: DUR.fast, easing: easeExit, onUpdate: apply, onComplete: collapse });
  }, [apply, onDelete, removing]);

  // Parent opens/closes (only one row open; tapping elsewhere closes).
  useEffect(() => {
    if (gesture.current?.locked === "x" || removing) return;
    settle(open ? -REVEAL : 0);
  }, [open, removing, settle]);

  useEffect(() => () => cancelRef.current?.(), []);

  if (!onDelete) return <li className="lib-row" data-row-key={rowKey}>{children}</li>;

  return (
    <li
      ref={rowRef}
      data-row-key={rowKey}
      className={removing ? "lib-row is-removing" : "lib-row"}
      onTransitionEnd={(event) => {
        if (removing && event.target === rowRef.current && event.propertyName === "height") onDelete();
      }}
    >
      <div className="lib-delete-layer" aria-hidden={!open}>
        <button type="button" className="lib-delete" onClick={remove} aria-label={deleteLabel} tabIndex={open ? 0 : -1}>
          删除
        </button>
      </div>
      <div
        ref={bodyRef}
        className="lib-row-body"
        onPointerDown={(event) => {
          cancelRef.current?.();
          const tracker = new VelocityTracker();
          tracker.reset(performance.now(), offsetRef.current);
          gesture.current = { x: event.clientX, y: event.clientY, base: offsetRef.current, locked: null, tracker };
          movedRef.current = false;
        }}
        onPointerMove={(event) => {
          const g = gesture.current;
          if (!g) return;
          const dx = event.clientX - g.x;
          const dy = event.clientY - g.y;
          if (!g.locked && (Math.abs(dx) > LOCK_DISTANCE || Math.abs(dy) > LOCK_DISTANCE)) {
            g.locked = Math.abs(dx) > Math.abs(dy) ? "x" : "y";
            if (g.locked === "x") {
              event.currentTarget.setPointerCapture(event.pointerId);
              event.currentTarget.style.willChange = "transform";
              movedRef.current = true;
            }
          }
          if (g.locked !== "x") return;
          const raw = g.base + dx;
          apply(Math.min(0, raw));
          g.tracker.add(performance.now(), offsetRef.current);
        }}
        onPointerUp={(event) => {
          const g = gesture.current;
          gesture.current = null;
          event.currentTarget.style.willChange = "";
          if (!g || g.locked !== "x") {
            if (g && open && !movedRef.current) settle(-REVEAL);
            return;
          }
          const decision = swipeDecision(offsetRef.current, rowRef.current?.offsetWidth ?? 360, g.tracker.velocity(performance.now()));
          if (decision === "delete") {
            remove();
            return;
          }
          const velocity = g.tracker.velocity(performance.now());
          settle(decision === "open" ? -REVEAL : 0, velocity);
          onOpenChange(decision === "open");
        }}
        onPointerCancel={() => {
          gesture.current = null;
          settle(open ? -REVEAL : 0);
        }}
        onClickCapture={(event) => {
          if (movedRef.current) {
            // The click that ends a swipe.
            event.preventDefault();
            event.stopPropagation();
            movedRef.current = false;
            return;
          }
          if (open) {
            event.preventDefault();
            event.stopPropagation();
            onOpenChange(false);
          }
        }}
      >
        {children}
      </div>
    </li>
  );
}
