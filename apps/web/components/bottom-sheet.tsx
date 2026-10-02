"use client";

import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";

import { attachDragDismiss, sheetTimings, type DragDismiss } from "../lib/motion/drag-dismiss";
import { DUR, tween } from "../lib/motion/easing";
import { scrimOpacityForOffset } from "../lib/motion/gesture";
import { useOverlay } from "../lib/overlay-stack";
import { Portal } from "./portal";

/**
 * Bottom sheet (MOTION.md §4.2): enters from translateY(100%) in 350ms
 * (ease-enter), leaves in 250ms (ease-exit), drag-to-dismiss from anywhere
 * (scrollable content hands over once it is at its top), interruptible.
 * Focus moves to the sheet title and returns to the trigger on close.
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
  const [rendered, setRendered] = useState(open);
  const panelRef = useRef<HTMLElement | null>(null);
  // The panel mounts through a portal after a tick; effects key off the node.
  const [panelNode, setPanelNode] = useState<HTMLElement | null>(null);
  const scrimRef = useRef<HTMLDivElement | null>(null);
  const controllerRef = useRef<DragDismiss | null>(null);
  const exitingRef = useRef(false);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const cancelFadeRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    if (open) {
      exitingRef.current = false;
      returnFocusRef.current = document.activeElement as HTMLElement | null;
      setRendered(true);
    }
  }, [open]);

  const panelHeight = () => panelRef.current?.offsetHeight || 600;

  const render = (offset: number) => {
    const panel = panelRef.current;
    if (panel) panel.style.transform = offset ? `translate3d(0, ${offset}px, 0)` : "";
    if (scrimRef.current) scrimRef.current.style.opacity = String(scrimOpacityForOffset(offset, panelHeight()));
  };

  const unmount = () => {
    setRendered(false);
    const target = returnFocusRef.current;
    returnFocusRef.current = null;
    if (target && document.contains(target)) target.focus({ preventScroll: true });
  };

  const exit = (velocity = 0) => {
    if (exitingRef.current) return;
    exitingRef.current = true;
    const timings = sheetTimings("sheet");
    const controller = controllerRef.current;
    if (!controller || timings.reduced) {
      const panel = panelRef.current;
      cancelFadeRef.current?.();
      cancelFadeRef.current = tween({
        from: 1,
        to: 0,
        duration: DUR.fast,
        onUpdate: (value) => {
          if (panel) panel.style.opacity = String(value);
          if (scrimRef.current) scrimRef.current.style.opacity = String(value);
        },
        onComplete: unmount,
      });
      return;
    }
    if (velocity > 0) controller.animateTo(panelHeight(), { velocity }, unmount);
    else controller.animateTo(panelHeight(), { duration: timings.exit.duration, easing: timings.exit.easing, spring: false }, unmount);
  };

  // Parent closed it (button, Escape, scrim): animate out, then unmount.
  useEffect(() => {
    if (!open && rendered) exit();
  }, [open]);

  // Attach drag + run the enter animation once mounted.
  useLayoutEffect(() => {
    const panel = panelNode;
    if (!rendered || !panel) return;
    const controller = attachDragDismiss({
      panel,
      height: panelHeight,
      render,
      onDismiss: (velocity) => {
        exit(Math.max(velocity, 0.01));
        onCloseRef.current();
      },
    });
    controllerRef.current = controller;
    const timings = sheetTimings("sheet");
    if (timings.reduced) {
      panel.style.transform = "";
      panel.style.opacity = "0";
      cancelFadeRef.current = tween({
        from: 0,
        to: 1,
        duration: DUR.fast,
        onUpdate: (value) => {
          panel.style.opacity = String(value);
          if (scrimRef.current) scrimRef.current.style.opacity = String(value);
        },
      });
    } else {
      controller.setOffset(panelHeight());
      controller.animateTo(0, { duration: timings.enter.duration, easing: timings.enter.easing, spring: false });
    }
    const title = panel.querySelector<HTMLElement>("h2, [data-sheet-title]");
    if (title) {
      if (!title.hasAttribute("tabindex")) title.setAttribute("tabindex", "-1");
      title.focus({ preventScroll: true });
    } else {
      panel.focus({ preventScroll: true });
    }
    return () => {
      cancelFadeRef.current?.();
      controller.detach();
      controllerRef.current = null;
    };
  }, [panelNode, rendered]);

  // Esc (and, on Android, Back) closes the top-most overlay.
  useOverlay(open, () => onCloseRef.current());

  if (!rendered) return null;

  return (
    <Portal>
      <div className="sheet-layer" role="presentation">
        <div ref={scrimRef} className="sheet-scrim" style={{ opacity: 0 }} onClick={() => onCloseRef.current()} aria-hidden="true" />
        <section
          ref={(node) => {
            panelRef.current = node;
            setPanelNode(node);
          }}
          tabIndex={-1}
          role="dialog"
          aria-modal="true"
          aria-label={label}
          className={`sheet sheet-${tone}${className ? " " + className : ""}`}
          style={{ height, transform: "translate3d(0, 100%, 0)" }}
        >
          <div className="sheet-handle-zone" data-drag-handle>
            <span className="sheet-handle" aria-hidden="true" />
          </div>
          {children}
        </section>
      </div>
    </Portal>
  );
}
