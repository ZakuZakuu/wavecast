"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

import { prefersReducedMotion } from "../../lib/motion/easing";
import { animateSpring, type Cancel } from "../../lib/motion/spring";
import { PULL_HOLD, PULL_MIN_REFRESH_MS, PULL_THRESHOLD, pullOffset, pullProgress } from "../../lib/pull-refresh";
import { LogoLine } from "../logo-line";

const SLOP = 8;

/**
 * Pull the page down from the top to refresh (Frost-Home2): the content follows the finger and the logo
 * is drawn in the space it uncovers; past the threshold it pops, and on release the antenna swings while
 * `onRefresh` runs. Without `canRefresh` a long pull springs back and calls `onBlocked` (guests).
 * The state lives here so the page below is not re-rendered on every touch move.
 */
export function PullToRefresh({
  children,
  canRefresh,
  onRefresh,
  onBlocked,
}: {
  children: ReactNode;
  canRefresh: boolean;
  onRefresh: () => Promise<unknown>;
  onBlocked: () => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const latest = useRef({ canRefresh, onRefresh, onBlocked });
  latest.current = { canRefresh, onRefresh, onBlocked };
  const [offset, setOffset] = useState(0);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    const scroller = host.current?.closest<HTMLElement>(".app-scroll");
    if (!scroller) return;
    let start: { x: number; y: number } | null = null;
    let pulling = false;
    let busy = false;
    let current = 0;
    let cancel: Cancel | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const show = (value: number) => {
      current = value;
      setOffset(value);
    };
    const settle = (to: number, done?: () => void) => {
      cancel?.();
      if (prefersReducedMotion()) {
        show(to);
        done?.();
        return;
      }
      cancel = animateSpring({ from: current, to, onUpdate: show, onComplete: done });
    };
    const refresh = () => {
      busy = true;
      setRefreshing(true);
      settle(PULL_HOLD);
      const startedAt = performance.now();
      void Promise.resolve(latest.current.onRefresh()).catch(() => undefined).then(() => {
        timer = setTimeout(() => {
          setRefreshing(false);
          settle(0, () => { busy = false; });
        }, Math.max(0, PULL_MIN_REFRESH_MS - (performance.now() - startedAt)));
      });
    };
    const release = () => {
      if (current < PULL_THRESHOLD) return settle(0);
      if (latest.current.canRefresh) return refresh();
      latest.current.onBlocked();
      settle(0);
    };

    const onStart = (event: TouchEvent) => {
      start = !busy && event.touches.length === 1 && scroller.scrollTop <= 0
        ? { x: event.touches[0].clientX, y: event.touches[0].clientY }
        : null;
      if (start) cancel?.();
    };
    const onMove = (event: TouchEvent) => {
      if (!start) return;
      const dx = event.touches[0].clientX - start.x;
      const dy = event.touches[0].clientY - start.y;
      if (!pulling) {
        if (Math.abs(dx) < SLOP && Math.abs(dy) < SLOP) return;
        // Upwards, sideways (the station row) or already scrolled: leave it to the browser.
        if (dy <= 0 || Math.abs(dx) > Math.abs(dy) || scroller.scrollTop > 0) {
          start = null;
          return;
        }
        pulling = true;
      }
      if (event.cancelable) event.preventDefault();
      show(pullOffset(dy));
    };
    const onEnd = () => {
      start = null;
      if (!pulling) return;
      pulling = false;
      release();
    };

    scroller.addEventListener("touchstart", onStart, { passive: true });
    scroller.addEventListener("touchmove", onMove, { passive: false });
    scroller.addEventListener("touchend", onEnd);
    scroller.addEventListener("touchcancel", onEnd);
    return () => {
      scroller.removeEventListener("touchstart", onStart);
      scroller.removeEventListener("touchmove", onMove);
      scroller.removeEventListener("touchend", onEnd);
      scroller.removeEventListener("touchcancel", onEnd);
      cancel?.();
      clearTimeout(timer);
    };
  }, []);

  const ready = offset >= PULL_THRESHOLD;
  return (
    <div ref={host}>
      {/* The logo rides down with the content and rests in the uncovered gap once the pull is ready. */}
      <div className="pull-logo" aria-hidden="true" style={{ opacity: offset > 0 ? 1 : 0, transform: `translateY(${offset - PULL_THRESHOLD}px)` }}>
        <LogoLine progress={refreshing ? 1 : pullProgress(offset)} swing={refreshing} bump={ready && !refreshing} />
      </div>
      <div className="pull-content" style={offset ? { transform: `translateY(${offset}px)` } : undefined}>
        {children}
      </div>
    </div>
  );
}
