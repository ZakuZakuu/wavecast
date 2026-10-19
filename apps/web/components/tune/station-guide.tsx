"use client";

import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type RefObject } from "react";

import { rgba } from "../../lib/cover/styled/color";
import { prefersReducedMotion } from "../../lib/motion/easing";
import { useOverlay } from "../../lib/overlay-stack";
import { hostLevel, STATION_GUIDES } from "../../lib/station-guide";
import { hostChoiceLabel, STATIONS, type Station } from "../../lib/stations";
import { stationBlends } from "../../lib/tuner";
import { ChevronLeftIcon, ChevronRightIcon, FillIcon } from "../icons";
import { DialSlider } from "./dial-slider";
import { TunerFace } from "./tuner-face";
import type { Tuner } from "./use-tuner";

type Box = { left: number; top: number; width: number; height: number };
type Phase = "closed" | "opening" | "open" | "closing";

/** How long the card takes to grow out of, and shrink back into, the tuner card (440ms in tune.css, plus a beat). */
const MOVE_MS = 480;

/** Three bars: how much the host talks. */
function HostBars({ level, color }: { level: 1 | 2 | 3; color: string }) {
  return (
    <span className="sg-bars" aria-hidden="true">
      {[1, 2, 3].map((index) => (
        <span key={index} style={{ height: 4 + index * 4, background: index <= level ? color : "rgba(29, 29, 31, .14)" }} />
      ))}
    </span>
  );
}

/** One station's page of the guide: what to tell it, what it does, how it hosts, three things to write. */
function StationPage({ station, weight, onPick }: { station: Station; weight: number; onPick: (station: Station, text: string) => void }) {
  const guide = STATION_GUIDES[station.id];
  const hidden = weight <= 0;
  return (
    <div
      className="sg-page"
      style={{ opacity: weight, visibility: hidden ? "hidden" : undefined, "--deep": station.deep, "--deep-text": station.deepText, "--chip-bg": rgba(station.light, 0.18) } as CSSProperties}
      inert={weight < 0.5}
      aria-hidden={weight < 0.5 ? true : undefined}
    >
      <div className="sg-give">
        <span className="sg-give-label">可以告诉它</span>
        <span className="sg-give-text">{guide.give.map((line, index) => (index === 0 ? line : <span key={line}><br />{line}</span>))}</span>
      </div>
      <p className="sg-pos">{guide.positioning[0]}<br />{guide.positioning[1]}</p>
      <div className="sg-host-row">
        <span className="sg-host">主持<HostBars level={hostLevel(station.host)} color={station.light} /><b>{hostChoiceLabel(station.host)}</b></span>
        <span className="sg-fill-note">点一条，填进输入框</span>
      </div>
      <div className="sg-scenes">
        {guide.scenes.map((scene) => (
          <button key={scene.text} type="button" className="sg-scene" onClick={() => onPick(station, scene.text)}>
            <span className="sg-tag">{scene.tag}</span>
            <span className="sg-text">{scene.display ? <>{scene.display[0]}<br />{scene.display[1]}</> : scene.text}</span>
            <FillIcon size={16} strokeWidth={2.2} />
          </button>
        ))}
      </div>
    </div>
  );
}

/**
 * The 电台指南: the tuner card grows into one page per station, over the page dimmed behind it. Swiping the card or
 * dragging its dial moves the very same tuner as the page's, so there is nothing to confirm: 选择 simply closes it,
 * and the page is on the station that was showing. Tapping a thing to write chooses the station and fills the box.
 */
export function StationGuide({
  tuner,
  open,
  first,
  originRef,
  onClose,
  onPick,
}: {
  tuner: Tuner;
  open: boolean;
  /** The first visit, which opened by itself: a bolder hint to swipe. */
  first: boolean;
  /** The card on the page, to grow out of and shrink back into. */
  originRef: RefObject<HTMLElement | null>;
  onClose: () => void;
  onPick: (station: Station, text: string) => void;
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const slotRef = useRef<HTMLDivElement>(null);
  const cardRef = useRef<HTMLElement>(null);
  const [phase, setPhase] = useState<Phase>("closed");
  const [box, setBox] = useState<Box | null>(null);

  const relative = (element: Element | null): Box | null => {
    const root = rootRef.current;
    if (!element || !root) return null;
    const a = element.getBoundingClientRect();
    const r = root.getBoundingClientRect();
    return { left: a.left - r.left, top: a.top - r.top, width: a.width, height: a.height };
  };

  // Open: start exactly on the tuner card, then (next frames) move to the full-size slot; close: the way back.
  useEffect(() => {
    if (open && phase === "closed") {
      setBox(relative(originRef.current));
      setPhase("opening");
    } else if (!open && (phase === "opening" || phase === "open")) {
      setBox(relative(originRef.current));
      setPhase("closing");
    }
    // `phase` is the machine's own state; only `open` drives it.
  }, [open]);

  useLayoutEffect(() => {
    if (phase !== "opening") return;
    let second = 0;
    const first = requestAnimationFrame(() => {
      second = requestAnimationFrame(() => {
        setBox(relative(slotRef.current));
        setPhase("open");
      });
    });
    return () => {
      cancelAnimationFrame(first);
      cancelAnimationFrame(second);
    };
  }, [phase]);

  useEffect(() => {
    if (phase !== "closing") return;
    const timer = window.setTimeout(() => {
      setPhase("closed");
      setBox(null);
    }, prefersReducedMotion() ? 0 : MOVE_MS);
    return () => window.clearTimeout(timer);
  }, [phase]);

  // The slot follows the screen (rotation, the address bar) while the guide is open.
  useEffect(() => {
    if (phase !== "open" || typeof ResizeObserver === "undefined" || !rootRef.current) return;
    const observer = new ResizeObserver(() => setBox(relative(slotRef.current)));
    observer.observe(rootRef.current);
    return () => observer.disconnect();
  }, [phase]);

  useEffect(() => {
    if (phase === "open") cardRef.current?.focus({ preventScroll: true });
  }, [phase]);

  useOverlay(phase === "opening" || phase === "open", onClose);

  const { station } = tuner;
  const blends = stationBlends(tuner.freq);
  const showing = phase === "open";
  return (
    <div ref={rootRef} className="sg" aria-hidden={phase === "closed" ? true : undefined}>
      <div ref={slotRef} className="sg-slot" aria-hidden="true" />
      {phase !== "closed" && box ? (
        <>
          <div className={showing ? "sg-scrim is-on" : "sg-scrim"} aria-hidden="true" onClick={onClose} />
          <section
            ref={cardRef}
            role="dialog"
            aria-modal="true"
            aria-label="电台指南"
            tabIndex={-1}
            className={showing ? "tuner-card sg-card is-expanded" : "tuner-card sg-card"}
            style={{ left: box.left, top: box.top, width: box.width, height: box.height, "--card-shadow": rgba(station.light, 0.3), touchAction: "pan-y" } as CSSProperties}
            {...tuner.swipe}
          >
            <TunerFace freq={tuner.freq} />
            <div className={showing ? "sg-fade is-on" : "sg-fade"}>
              <div className="sg-body">
                <div className="sg-stack">
                  {STATIONS.map((item, index) => (
                    <StationPage key={item.id} station={item} weight={blends[index].weight} onPick={onPick} />
                  ))}
                </div>
              </div>
              <button
                type="button"
                className="sg-choose"
                style={{ background: rgba(station.light, 0.24), color: station.deepText }}
                onClick={onClose}
              >
                选择
              </button>
              <div className={first ? "sg-hint is-first" : "sg-hint"}>
                <span><ChevronLeftIcon size={14} strokeWidth={2.6} /></span>
                {first ? "左右滑动，看看每个台" : "左右滑动，换台"}
                <span><ChevronRightIcon size={14} strokeWidth={2.6} /></span>
              </div>
            </div>
            <DialSlider
              freq={tuner.freq}
              reading={tuner.reading}
              station={station}
              dragging={tuner.dragging}
              handlers={tuner.dial}
              onKeyDown={tuner.dial.onKeyDown}
            />
          </section>
        </>
      ) : null}
    </div>
  );
}
