"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { easeStandard, prefersReducedMotion, tween } from "../../lib/motion/easing";
import { VelocityTracker } from "../../lib/motion/gesture";
import { animateSpring, type Cancel } from "../../lib/motion/spring";
import { FIRST_VISIT_STATION_ID, FREQ_MAX, FREQ_MIN, stationById, type Station } from "../../lib/stations";
import {
  clampFreq,
  freqAfterDrag,
  nearestStation,
  neighbourStation,
  PX_PER_MHZ,
  readTuner,
  stepStation,
  WHEEL_SNAP_DELAY_MS,
  wheelDeltaPx,
  type TunerReading,
} from "../../lib/tuner";
import { LAST_STATION_KEY } from "./use-tune-start";

const MATCH_SLIDE_MS = 500;
/** Inertia: velocity decays to 0.998× per ms (iOS normal scrolling). */
const GLIDE_DECAY_PER_MS = 0.998;
/** Below this speed (px/ms) the glide hands over to the snapping spring. */
const GLIDE_STOP_SPEED = 0.05;
/** A swipe on the card body starts once the finger has gone this far sideways, and further sideways than up or down. */
const SWIPE_START_PX = 8;

type DragState = {
  x: number;
  y: number;
  freq: number;
  tracker: VelocityTracker;
  /** The station name that was pressed, so that a tap tunes straight to it. */
  label: string | null;
  moved: boolean;
  /** Pointer capture taken: a dial drag has it from the start, a card swipe once it is clearly sideways. */
  captured: boolean;
};

export type TunerPointerHandlers = {
  onPointerDown: (event: React.PointerEvent<HTMLElement>) => void;
  onPointerMove: (event: React.PointerEvent<HTMLElement>) => void;
  onPointerUp: (event: React.PointerEvent<HTMLElement>) => void;
  onPointerCancel: (event: React.PointerEvent<HTMLElement>) => void;
};

export type Tuner = {
  freq: number;
  reading: TunerReading;
  station: Station;
  dragging: boolean;
  /** The page's dial window, which the wheel scrolls (set by the dial itself). */
  dialRef: React.MutableRefObject<HTMLDivElement | null>;
  /** Drag the dial (the dial window, and the grip under it). */
  dial: TunerPointerHandlers & { onKeyDown: (event: React.KeyboardEvent) => void };
  /** Swipe sideways anywhere on a card to change station; leaves taps and vertical scrolling alone. */
  swipe: TunerPointerHandlers & { onClickCapture: (event: React.MouseEvent) => void };
  tuneTo: (station: Station) => void;
  /** Move straight to a station, no slide (the card has not been seen yet). */
  jumpTo: (station: Station) => void;
  /** One station down (-1) or up (1) the band, from where a slide in progress is heading. */
  step: (direction: 1 | -1) => void;
  /** Whether there is a station that way, for the dial's end buttons. */
  canStep: { down: boolean; up: boolean };
};

/**
 * The tuner: one frequency, dragged (dial or card), flung, snapped to the nearest station, stepped with the keyboard
 * or the wheel, or slid to a station. The tuner page and the 电台指南 share one instance, so swiping the guide moves
 * the page's dial and closing the guide leaves the page on the station that was showing.
 */
export function useTuner(): Tuner {
  const [freq, setFreqState] = useState(() => stationById(FIRST_VISIT_STATION_ID).freq);
  const freqRef = useRef(freq);
  const [dragging, setDragging] = useState(false);
  const animRef = useRef<Cancel | null>(null);
  /** The station a slide or snap is heading for, so that repeated taps on a step button keep going. */
  const headingRef = useRef<Station | null>(null);
  const lastLockedRef = useRef<string | null>(null);
  const dragState = useRef<DragState | null>(null);
  const justSwiped = useRef(false);
  // The page's dial window, for the wheel; the dial measures its own width.
  const dialRef = useRef<HTMLDivElement | null>(null);

  const setFreq = useCallback((value: number) => {
    const next = clampFreq(value);
    freqRef.current = next;
    setFreqState(next);
  }, []);

  const stopAnimation = useCallback(() => {
    animRef.current?.();
    animRef.current = null;
    headingRef.current = null;
  }, []);

  /** Slide the scale to a station (tap, keyboard, home card): 500ms ease-standard. */
  const animateTo = useCallback((target: number, durationMs = MATCH_SLIDE_MS) => {
    stopAnimation();
    if (prefersReducedMotion()) {
      setFreq(target);
      return;
    }
    headingRef.current = nearestStation(target).station;
    animRef.current = tween({
      from: freqRef.current,
      to: target,
      duration: durationMs,
      easing: easeStandard,
      onUpdate: setFreq,
      onComplete: () => {
        animRef.current = null;
        headingRef.current = null;
      },
    });
  }, [setFreq, stopAnimation]);

  /** Spring onto the nearest station, carrying the release velocity (px/ms). */
  const snapWithSpring = useCallback((velocityPx: number) => {
    stopAnimation();
    const nearest = readTuner(freqRef.current).station;
    const target = nearest.freq;
    if (prefersReducedMotion()) {
      setFreq(target);
      return;
    }
    headingRef.current = nearest;
    animRef.current = animateSpring({
      from: freqRef.current * PX_PER_MHZ,
      to: target * PX_PER_MHZ,
      velocity: velocityPx,
      epsilon: 0.2,
      onUpdate: (px) => setFreq(px / PX_PER_MHZ),
      onComplete: () => {
        animRef.current = null;
        headingRef.current = null;
      },
    });
  }, [setFreq, stopAnimation]);

  /** Inertial glide, then spring snap once slower than GLIDE_STOP_SPEED. */
  const glide = useCallback((initialVelocityPx: number) => {
    stopAnimation();
    let velocity = initialVelocityPx;
    let last = performance.now();
    let frame = requestAnimationFrame(function step(now) {
      const dt = Math.min(64, now - last);
      last = now;
      const decayed = velocity * Math.pow(GLIDE_DECAY_PER_MS, dt);
      // Distance covered while decaying exponentially over dt.
      const travel = (velocity - decayed) / -Math.log(GLIDE_DECAY_PER_MS);
      velocity = decayed;
      const next = clampFreq(freqRef.current + travel / PX_PER_MHZ);
      setFreq(next);
      const atEdge = next <= FREQ_MIN || next >= FREQ_MAX;
      if (Math.abs(velocity) < GLIDE_STOP_SPEED || atEdge) {
        animRef.current = null;
        snapWithSpring(atEdge ? 0 : velocity);
        return;
      }
      frame = requestAnimationFrame(step);
    });
    animRef.current = () => cancelAnimationFrame(frame);
  }, [setFreq, snapWithSpring, stopAnimation]);

  // First station: ?station= from a home card, else the last one tuned, else the first-visit station.
  // Before the first paint, so that a returning listener never sees the first-visit station flash by.
  useLayoutEffect(() => {
    let fromQuery: Station | null = null;
    let last: Station | null = null;
    const id = new URLSearchParams(window.location.search).get("station");
    fromQuery = id ? stationById(id) : null;
    try {
      const lastId = window.localStorage.getItem(LAST_STATION_KEY);
      last = lastId ? stationById(lastId) : null;
    } catch {
      // Storage blocked: the first-visit station, or the one the link asks for.
    }
    if (last) setFreq(last.freq);
    // From a home station card: slide from where the dial was to that station.
    if (fromQuery && Math.abs(fromQuery.freq - freqRef.current) > 0.01) animateTo(fromQuery.freq);
    return stopAnimation;
  }, [animateTo, setFreq, stopAnimation]);

  const reading = readTuner(freq);
  const station = reading.station;

  // Light haptic tick when a station locks in (Android; iOS web ignores it).
  useEffect(() => {
    if (reading.locked && lastLockedRef.current !== station.id) {
      lastLockedRef.current = station.id;
      try {
        navigator.vibrate?.(8);
      } catch {
        // Unsupported.
      }
    } else if (!reading.locked) {
      lastLockedRef.current = null;
    }
  }, [reading.locked, station.id]);

  const startDrag = (event: React.PointerEvent<HTMLElement>, captured: boolean): void => {
    // Grabbing the dial stops what it was doing. A press on the card might only be a tap (on the picture, on the
    // link), which must leave a slide in progress alone, so that stops only once it turns into a swipe.
    if (captured) {
      stopAnimation();
      event.currentTarget.setPointerCapture(event.pointerId);
    }
    const label = (event.target as HTMLElement).closest?.("[data-station]")?.getAttribute("data-station") ?? null;
    const tracker = new VelocityTracker();
    tracker.reset(performance.now(), freqRef.current * PX_PER_MHZ);
    dragState.current = { x: event.clientX, y: event.clientY, freq: freqRef.current, tracker, label, moved: false, captured };
    if (captured) setDragging(true);
  };

  const moveDrag = (event: React.PointerEvent<HTMLElement>): void => {
    const drag = dragState.current;
    if (!drag) return;
    // A mouse button released outside the card never reached it: this is not a drag, whatever the press said.
    if (event.pointerType === "mouse" && event.buttons === 0) {
      dragState.current = null;
      if (drag.captured) {
        setDragging(false);
        snapWithSpring(0);
      }
      return;
    }
    const dx = event.clientX - drag.x;
    if (!drag.captured) {
      // A card swipe: wait until it is clearly sideways, then take the pointer and start from here.
      const dy = event.clientY - drag.y;
      if (Math.abs(dx) < SWIPE_START_PX || Math.abs(dx) < Math.abs(dy) * 1.2) return;
      stopAnimation();
      event.currentTarget.setPointerCapture(event.pointerId);
      drag.captured = true;
      drag.x = event.clientX;
      drag.freq = freqRef.current;
      drag.tracker.reset(performance.now(), freqRef.current * PX_PER_MHZ);
      setDragging(true);
      return;
    }
    if (Math.abs(dx) > 4) drag.moved = true;
    const next = freqAfterDrag(drag.freq, dx);
    setFreq(next);
    drag.tracker.add(performance.now(), next * PX_PER_MHZ);
  };

  const tuneTo = useCallback((target: Station) => animateTo(target.freq), [animateTo]);
  const step = useCallback((direction: 1 | -1) => {
    // From where a slide in progress is heading, else from where the dial is: two quick taps are two stations.
    const next = neighbourStation(headingRef.current?.freq ?? freqRef.current, direction);
    if (next) animateTo(next.freq);
  }, [animateTo]);
  const jumpTo = useCallback((target: Station) => {
    stopAnimation();
    setFreq(target.freq);
  }, [setFreq, stopAnimation]);

  const endDrag = (): void => {
    const drag = dragState.current;
    dragState.current = null;
    setDragging(false);
    // A tap that never became a swipe: nothing was moved, nothing to settle.
    if (!drag || !drag.captured) return;
    if (!drag.moved && drag.label) {
      // A tap on a station name tunes straight to it.
      tuneTo(stationById(drag.label));
      return;
    }
    // Velocity over the last 80ms, in px/ms of scale travel.
    const velocity = drag.tracker.velocity(performance.now());
    if (prefersReducedMotion()) {
      snapWithSpring(0);
      return;
    }
    if (Math.abs(velocity) < GLIDE_STOP_SPEED) snapWithSpring(velocity);
    else glide(velocity);
  };

  // Whatever happened (a tap that stopped a slide, a lost pointer), the dial never rests between two stations.
  useEffect(() => {
    if (dragging) return;
    const timer = window.setTimeout(() => {
      if (dragState.current?.captured || animRef.current) return;
      const { station: nearest } = nearestStation(freqRef.current);
      if (Math.abs(nearest.freq - freqRef.current) > 1e-3) snapWithSpring(0);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [freq, dragging, snapWithSpring]);

  // Mouse wheel / trackpad: scroll moves the scale, snapping 150ms after it stops.
  useEffect(() => {
    const element = dialRef.current;
    if (!element) return;
    let timer = 0;
    const onWheel = (event: WheelEvent) => {
      const delta = wheelDeltaPx(event, element.clientWidth);
      if (!delta) return;
      event.preventDefault();
      stopAnimation();
      setFreq(freqRef.current + delta / PX_PER_MHZ);
      window.clearTimeout(timer);
      timer = window.setTimeout(() => snapWithSpring(0), WHEEL_SNAP_DELAY_MS);
    };
    element.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      element.removeEventListener("wheel", onWheel);
      window.clearTimeout(timer);
    };
  }, [dialRef, setFreq, snapWithSpring, stopAnimation]);

  const dial = {
    onPointerDown: (event: React.PointerEvent<HTMLElement>) => {
      if (event.button !== 0 && event.pointerType === "mouse") return;
      startDrag(event, true);
    },
    onPointerMove: moveDrag,
    onPointerUp: endDrag,
    onPointerCancel: endDrag,
    onKeyDown: (event: React.KeyboardEvent) => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      event.preventDefault();
      animateTo(stepStation(freqRef.current, event.key === "ArrowRight" ? 1 : -1).freq);
    },
  };

  const swipe = {
    onPointerDown: (event: React.PointerEvent<HTMLElement>) => {
      if (event.button !== 0 && event.pointerType === "mouse") return;
      // A press on the dial itself is the dial's: it has its own handlers and its own capture.
      if ((event.target as HTMLElement).closest?.("[data-tuner-dial]")) return;
      startDrag(event, false);
    },
    onPointerMove: moveDrag,
    onPointerUp: () => {
      const swiped = Boolean(dragState.current?.captured);
      endDrag();
      // The click that follows a swipe must not press whatever the finger lifted over.
      if (swiped) {
        justSwiped.current = true;
        window.setTimeout(() => { justSwiped.current = false; }, 0);
      }
    },
    onPointerCancel: endDrag,
    onClickCapture: (event: React.MouseEvent) => {
      if (!justSwiped.current) return;
      event.preventDefault();
      event.stopPropagation();
    },
  };

  const heading = headingRef.current?.freq ?? freq;
  const canStep = { down: neighbourStation(heading, -1) !== null, up: neighbourStation(heading, 1) !== null };
  return { freq, reading, station, dragging, dialRef, dial, swipe, tuneTo, jumpTo, step, canStep };
}

