"use client";

import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { DUR, easeEnter, easeExit, prefersReducedMotion, tween } from "../../lib/motion/easing";
import { attachDragDismiss, type DragDismiss } from "../../lib/motion/drag-dismiss";
import { lastTabPathOr } from "../../lib/nav-memory";
import { useOverlay } from "../../lib/overlay-stack";
import {
  miniCoverTargetRect,
  playerOpenedInApp,
  playerTargetFromPath,
  resetPlayerOpened,
  takeOpenSource,
  type PlayerTargetFromPath,
} from "../../lib/player-nav";
import { PlayerScreen } from "./player-screen";

const SCRIM_MAX = 0.3;

function targetKey(target: PlayerTargetFromPath | null): string {
  if (!target) return "";
  return target.episodeId ? "e:" + target.episodeId : "s:" + target.seedId;
}

type Flip = { dx: number; dy: number; scale: number } | null;

/**
 * The player as an overlay over the current page (MOTION.md §4.1): it slides
 * up from the bottom (the cover grows out of the mini player's thumbnail),
 * dims the page beneath to 0.3, follows a downward drag from the top 44px or
 * the cover, and collapses back into the mini player.
 */
export function PlayerOverlay() {
  const pathname = usePathname();
  const router = useRouter();
  const target = playerTargetFromPath(pathname);
  const [shown, setShown] = useState<PlayerTargetFromPath | null>(target);
  const phaseRef = useRef<"enter" | "open" | "exit">(target ? "open" : "exit");
  const layerRef = useRef<HTMLDivElement | null>(null);
  const sheetRef = useRef<HTMLDivElement | null>(null);
  const scrimRef = useRef<HTMLDivElement | null>(null);
  const controllerRef = useRef<DragDismiss | null>(null);
  const flipRef = useRef<Flip>(null);
  const cancelFadeRef = useRef<(() => void) | null>(null);
  const firstRenderRef = useRef(true);

  const height = () => sheetRef.current?.offsetHeight || window.innerHeight;

  const coverElement = () => sheetRef.current?.querySelector<HTMLElement>(".player-cover") ?? null;

  /** Untransformed cover position vs. a mini-player thumbnail rect. */
  const measureFlip = useCallback((mini: DOMRect | null): Flip => {
    const cover = coverElement();
    if (!mini || !cover || prefersReducedMotion()) return null;
    const previous = cover.style.transform;
    cover.style.transform = "";
    const rect = cover.getBoundingClientRect();
    cover.style.transform = previous;
    const sheetOffset = controllerRef.current?.offset() ?? 0;
    const finalTop = rect.top - sheetOffset;
    if (rect.width === 0) return null;
    return {
      dx: mini.left + mini.width / 2 - (rect.left + rect.width / 2),
      dy: mini.top + mini.height / 2 - (finalTop + rect.height / 2),
      scale: mini.width / rect.width,
    };
  }, []);

  const render = useCallback((offset: number) => {
    const sheet = sheetRef.current;
    if (!sheet) return;
    const h = height();
    const progress = Math.max(0, Math.min(1, offset / h)); // 0 open, 1 closed
    sheet.style.transform = offset ? `translate3d(0, ${offset}px, 0)` : "";
    if (scrimRef.current) scrimRef.current.style.opacity = String(SCRIM_MAX * (1 - progress));
    const cover = coverElement();
    const flip = flipRef.current;
    if (cover) {
      cover.style.transform = flip && offset > 0
        ? `translate3d(${progress * flip.dx}px, ${progress * flip.dy - offset}px, 0) scale(${1 + progress * (flip.scale - 1)})`
        : "";
    }
  }, []);

  const finishClose = useCallback((navigate: boolean) => {
    if (!navigate) {
      setShown(null);
      return;
    }
    // Keep the (now off-screen) overlay until the URL leaves the player.
    if (playerOpenedInApp()) {
      resetPlayerOpened();
      window.history.back();
    } else {
      router.push(lastTabPathOr("/"));
    }
  }, [router]);

  const close = useCallback((velocity: number, navigate: boolean) => {
    if (phaseRef.current === "exit") return;
    phaseRef.current = "exit";
    const controller = controllerRef.current;
    if (!controller || prefersReducedMotion()) {
      cancelFadeRef.current?.();
      const layer = layerRef.current;
      cancelFadeRef.current = tween({
        from: 1,
        to: 0,
        duration: DUR.fast,
        onUpdate: (value) => { if (layer) layer.style.opacity = String(value); },
        onComplete: () => finishClose(navigate),
      });
      return;
    }
    flipRef.current = measureFlip(miniCoverTargetRect());
    const done = () => finishClose(navigate);
    if (velocity > 0) controller.animateTo(height(), { velocity }, done);
    else controller.animateTo(height(), { duration: DUR.page, easing: easeExit, spring: false }, done);
  }, [finishClose, measureFlip]);

  // URL drives the overlay: entering a player path opens, leaving closes.
  useEffect(() => {
    if (firstRenderRef.current) {
      firstRenderRef.current = false;
      return;
    }
    if (target) {
      if (targetKey(target) !== targetKey(shown) || phaseRef.current === "exit") {
        phaseRef.current = "enter";
        setShown(target);
      }
    } else if (shown) {
      if (phaseRef.current === "exit") setShown(null);
      else close(0, false);
    }
  }, [pathname]);

  // Attach the drag controller to the sheet while it is shown.
  useLayoutEffect(() => {
    const sheet = sheetRef.current;
    if (!shown || !sheet) return;
    const controller = attachDragDismiss({
      panel: sheet,
      height,
      render,
      canStartFrom: (element) => Boolean(element.closest("[data-drag-handle]")),
      onDragStart: () => {
        phaseRef.current = "open";
        flipRef.current = measureFlip(miniCoverTargetRect());
      },
      onDismiss: (velocity) => close(Math.max(velocity, 0.01), true),
    });
    controllerRef.current = controller;
    return () => {
      controller.detach();
      controllerRef.current = null;
    };
  }, [close, measureFlip, render, shown]);

  // Enter animation when a new player target appears.
  const shownKey = targetKey(shown);
  useLayoutEffect(() => {
    if (!shown || phaseRef.current !== "enter") return;
    const controller = controllerRef.current;
    const layer = layerRef.current;
    const { source, rect } = takeOpenSource();
    if (!controller || !layer) return;
    layer.style.opacity = "";
    if (prefersReducedMotion() || source === "fade") {
      controller.setOffset(0);
      cancelFadeRef.current?.();
      layer.style.opacity = "0";
      cancelFadeRef.current = tween({
        from: 0,
        to: 1,
        duration: prefersReducedMotion() ? DUR.fast : DUR.slow,
        onUpdate: (value) => { layer.style.opacity = String(value); },
        onComplete: () => { phaseRef.current = "open"; },
      });
      return;
    }
    controller.setOffset(height());
    flipRef.current = measureFlip(rect);
    render(height());
    controller.animateTo(0, { duration: DUR.page, easing: easeEnter, spring: false }, () => {
      phaseRef.current = "open";
      flipRef.current = null;
    });
  }, [shownKey]);

  useEffect(() => () => cancelFadeRef.current?.(), []);

  // Esc collapses the player when nothing is open above it. Back needs no
  // extra entry: the player has its own URL.
  useOverlay(Boolean(shown), () => close(0, true), { history: false });

  if (!shown) return null;

  return (
    <div ref={layerRef} className="player-layer">
      <div ref={scrimRef} className="player-scrim" aria-hidden="true" />
      <div ref={sheetRef} className="player-sheet">
        <PlayerScreen
          key={targetKey(shown)}
          seedId={shown.seedId}
          episodeId={shown.episodeId}
          onCollapse={() => close(0, true)}
        />
      </div>
    </div>
  );
}
