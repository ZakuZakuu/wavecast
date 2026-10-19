"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import { DUR, easeExit, prefersReducedMotion, tween } from "../../lib/motion/easing";
import { VelocityTracker } from "../../lib/motion/gesture";
import { animateSpring, type Cancel } from "../../lib/motion/spring";

const ACTION_WIDTH = 84;
const OPEN_THRESHOLD = 40;
const DELETE_RATIO = 0.6;
const LOCK_DISTANCE = 6;

/** A button behind the row. The last one is what a long swipe commits, if it `removes` the row. */
export type SwipeAction = {
  label: string;
  ariaLabel: string;
  tone: "favourite" | "danger";
  /** Runs once the action is committed; a removing action first slides the row out and collapses it. */
  onPress: () => void;
  removes?: boolean;
};

/** Where a released swipe should settle (MOTION.md §4.10). `delete` = commit the last action. */
export function swipeDecision(
  offset: number,
  rowWidth: number,
  velocity: number,
  canCommit = true,
): "delete" | "open" | "close" {
  const revealed = -offset;
  if (canCommit && rowWidth > 0 && revealed > rowWidth * DELETE_RATIO) return "delete";
  if (velocity < -0.5) return "open";
  if (velocity > 0.5) return "close";
  return revealed > OPEN_THRESHOLD ? "open" : "close";
}

/**
 * Library row with swipe actions: follows the finger, springs to reveal the 84px buttons past 40px,
 * and past 60% of the row commits the last one when it removes the row (slides out, then the row
 * height collapses). Only one row is open at a time. No actions = a plain row.
 */
export function SwipeRow({
  children,
  actions,
  open,
  onOpenChange,
  rowKey,
}: {
  rowKey: string;
  children: ReactNode;
  actions: SwipeAction[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const reveal = ACTION_WIDTH * actions.length;
  const last = actions[actions.length - 1];
  const commitsLast = Boolean(last?.removes);
  const rowRef = useRef<HTMLLIElement | null>(null);
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const offsetRef = useRef(0);
  const cancelRef = useRef<Cancel | null>(null);
  const gesture = useRef<{ x: number; y: number; base: number; locked: "x" | "y" | null; tracker: VelocityTracker } | null>(null);
  const movedRef = useRef(false);
  const [removing, setRemoving] = useState(false);
  const committing = useRef<SwipeAction | null>(null);

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

  const remove = useCallback((action: SwipeAction) => {
    if (removing) return;
    committing.current = action;
    cancelRef.current?.();
    const width = rowRef.current?.offsetWidth ?? 360;
    const collapse = () => setRemoving(true);
    if (prefersReducedMotion()) {
      collapse();
      return;
    }
    cancelRef.current = tween({ from: offsetRef.current, to: -width, duration: DUR.fast, easing: easeExit, onUpdate: apply, onComplete: collapse });
  }, [apply, removing]);

  // Parent opens/closes (only one row open; tapping elsewhere closes).
  useEffect(() => {
    if (gesture.current?.locked === "x" || removing) return;
    settle(open ? -reveal : 0);
  }, [open, removing, reveal, settle]);

  useEffect(() => () => cancelRef.current?.(), []);

  if (!actions.length) return <li className="lib-row" data-row-key={rowKey}>{children}</li>;

  const press = (action: SwipeAction) => {
    if (action.removes) {
      remove(action);
      return;
    }
    action.onPress();
    onOpenChange(false);
  };

  return (
    <li
      ref={rowRef}
      data-row-key={rowKey}
      className={removing ? "lib-row is-removing" : "lib-row"}
      onTransitionEnd={(event) => {
        if (removing && event.target === rowRef.current && event.propertyName === "height") committing.current?.onPress();
      }}
    >
      <div className={`lib-actions-layer is-${last.tone}`} aria-hidden={!open}>
        {actions.map((action) => (
          <button
            key={action.label}
            type="button"
            className={`lib-action is-${action.tone}`}
            onClick={() => press(action)}
            aria-label={action.ariaLabel}
            tabIndex={open ? 0 : -1}
          >
            {action.label}
          </button>
        ))}
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
            if (g && open && !movedRef.current) settle(-reveal);
            return;
          }
          const decision = swipeDecision(offsetRef.current, rowRef.current?.offsetWidth ?? 360, g.tracker.velocity(performance.now()), commitsLast);
          if (decision === "delete") {
            remove(last);
            return;
          }
          const velocity = g.tracker.velocity(performance.now());
          settle(decision === "open" ? -reveal : 0, velocity);
          onOpenChange(decision === "open");
        }}
        onPointerCancel={() => {
          gesture.current = null;
          settle(open ? -reveal : 0);
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
