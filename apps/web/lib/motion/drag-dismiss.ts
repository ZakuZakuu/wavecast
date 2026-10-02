// Drag-to-dismiss controller for the player and every bottom sheet
// (MOTION.md §3). Framework-agnostic: it owns the offset and its animations,
// and calls `render` with the current offset (0 = open, height = closed).
import { DUR, easeEnter, easeExit, prefersReducedMotion, tween } from "./easing";
import { VelocityTracker, sheetDragOffset, shouldDismiss } from "./gesture";
import { animateSpring, type Cancel } from "./spring";

const START_THRESHOLD = 6;
const NO_DRAG = "button, a, input, textarea, select, [role='slider'], [data-no-drag]";

export type DragDismissOptions = {
  panel: HTMLElement;
  height: () => number;
  render: (offset: number) => void;
  /** Called when a released drag should close; the consumer animates out. */
  onDismiss: (velocity: number) => void;
  /** Where a drag may start. Default: anywhere except controls. */
  canStartFrom?: (target: Element) => boolean;
  onDragStart?: () => void;
  onDragEnd?: () => void;
};

export type DragDismiss = {
  detach: () => void;
  offset: () => number;
  setOffset: (offset: number) => void;
  /** Animate to a target (spring by default, carrying `velocity`). */
  animateTo: (
    target: number,
    options?: { velocity?: number; duration?: number; easing?: (t: number) => number; spring?: boolean },
    done?: () => void,
  ) => void;
  stop: () => void;
  dragging: () => boolean;
};

function nearestScrollable(target: Element, root: Element): HTMLElement | null {
  let node: Element | null = target;
  while (node && node !== root) {
    if (node instanceof HTMLElement) {
      const style = getComputedStyle(node);
      if (/(auto|scroll)/.test(style.overflowY) && node.scrollHeight > node.clientHeight + 1) return node;
    }
    node = node.parentElement;
  }
  return null;
}

export function attachDragDismiss(options: DragDismissOptions): DragDismiss {
  const { panel } = options;
  const tracker = new VelocityTracker();
  let offset = 0;
  let cancel: Cancel | null = null;
  let active: { startY: number; startX: number; base: number; dragging: boolean; scroller: HTMLElement | null; pointerId?: number } | null = null;

  const render = (value: number) => {
    offset = value;
    options.render(value);
  };

  const stop = () => {
    cancel?.();
    cancel = null;
  };

  const animateTo: DragDismiss["animateTo"] = (target, animation = {}, done) => {
    stop();
    if (animation.spring !== false && animation.duration === undefined) {
      cancel = animateSpring({
        from: offset,
        to: target,
        velocity: animation.velocity ?? 0,
        onUpdate: (value) => render(value),
        onComplete: () => {
          cancel = null;
          done?.();
        },
      });
      return;
    }
    cancel = tween({
      from: offset,
      to: target,
      duration: animation.duration ?? DUR.slow,
      easing: animation.easing ?? easeEnter,
      onUpdate: (value) => render(value),
      onComplete: () => {
        cancel = null;
        done?.();
      },
    });
  };

  const canStart = (target: Element) => {
    if (target.closest(NO_DRAG) && !target.closest("[data-drag-handle]")) return false;
    return options.canStartFrom ? options.canStartFrom(target) : true;
  };

  const begin = (x: number, y: number, target: Element, pointerId?: number) => {
    if (!canStart(target)) return false;
    active = { startX: x, startY: y, base: offset, dragging: false, scroller: nearestScrollable(target, panel), pointerId };
    tracker.reset(performance.now(), y);
    return true;
  };

  /** Returns true when this move is (now) a sheet drag. */
  const move = (x: number, y: number): boolean => {
    if (!active) return false;
    const dy = y - active.startY;
    const dx = x - active.startX;
    if (!active.dragging) {
      if (Math.abs(dy) < START_THRESHOLD && Math.abs(dx) < START_THRESHOLD) return false;
      if (Math.abs(dx) > Math.abs(dy)) {
        active = null;
        return false;
      }
      const scroller = active.scroller;
      // Content scrolls first; only at its top does a downward pull move the sheet.
      if (scroller && (dy < 0 || scroller.scrollTop > 0)) {
        active = null;
        return false;
      }
      // Grabbing mid-animation continues from the current position.
      stop();
      active.dragging = true;
      active.base = offset;
      active.startY = y; // avoid a jump by the threshold
      panel.style.willChange = "transform";
      options.onDragStart?.();
    }
    tracker.add(performance.now(), y);
    render(sheetDragOffset(active.base + (y - active.startY)));
    return true;
  };

  const end = () => {
    if (!active) return;
    const wasDragging = active.dragging;
    active = null;
    if (!wasDragging) return;
    panel.style.willChange = "";
    options.onDragEnd?.();
    const velocity = tracker.velocity(performance.now());
    if (shouldDismiss(offset, options.height(), velocity)) {
      options.onDismiss(velocity);
    } else {
      animateTo(0, { velocity });
    }
  };

  // Mouse/pen through pointer events; touch through touch events so a
  // scrollable list can hand over to the sheet once it reaches its top.
  const onPointerDown = (event: PointerEvent) => {
    if (event.pointerType === "touch" || event.button !== 0) return;
    if (begin(event.clientX, event.clientY, event.target as Element, event.pointerId)) {
      panel.setPointerCapture?.(event.pointerId);
    }
  };
  const onPointerMove = (event: PointerEvent) => {
    if (event.pointerType === "touch" || !active || active.pointerId !== event.pointerId) return;
    move(event.clientX, event.clientY);
  };
  const onPointerUp = (event: PointerEvent) => {
    if (event.pointerType === "touch") return;
    end();
  };
  const onTouchStart = (event: TouchEvent) => {
    if (event.touches.length !== 1) return;
    const touch = event.touches[0];
    begin(touch.clientX, touch.clientY, event.target as Element);
  };
  const onTouchMove = (event: TouchEvent) => {
    if (!active) return;
    const touch = event.touches[0];
    if (move(touch.clientX, touch.clientY) && event.cancelable) event.preventDefault();
  };
  const onTouchEnd = () => end();

  panel.addEventListener("pointerdown", onPointerDown);
  panel.addEventListener("pointermove", onPointerMove);
  panel.addEventListener("pointerup", onPointerUp);
  panel.addEventListener("pointercancel", onPointerUp);
  panel.addEventListener("touchstart", onTouchStart, { passive: true });
  panel.addEventListener("touchmove", onTouchMove, { passive: false });
  panel.addEventListener("touchend", onTouchEnd);
  panel.addEventListener("touchcancel", onTouchEnd);

  return {
    detach: () => {
      stop();
      panel.removeEventListener("pointerdown", onPointerDown);
      panel.removeEventListener("pointermove", onPointerMove);
      panel.removeEventListener("pointerup", onPointerUp);
      panel.removeEventListener("pointercancel", onPointerUp);
      panel.removeEventListener("touchstart", onTouchStart);
      panel.removeEventListener("touchmove", onTouchMove);
      panel.removeEventListener("touchend", onTouchEnd);
      panel.removeEventListener("touchcancel", onTouchEnd);
    },
    offset: () => offset,
    setOffset: (value) => {
      stop();
      render(value);
    },
    animateTo,
    stop,
    dragging: () => Boolean(active?.dragging),
  };
}

/** Enter/exit timing for sheets and the player, honouring reduced motion. */
export function sheetTimings(kind: "sheet" | "page") {
  const reduced = prefersReducedMotion();
  return {
    reduced,
    enter: { duration: reduced ? 0 : kind === "page" ? DUR.page : DUR.slow, easing: easeEnter },
    exit: { duration: reduced ? 0 : kind === "page" ? DUR.page : DUR.base, easing: easeExit },
    fade: DUR.fast,
  };
}
