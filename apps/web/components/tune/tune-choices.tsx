"use client";

import { useLayoutEffect, useRef, useState } from "react";

import { DURATION_CHIPS, HOST_CHOICES, hostChoiceLabel, type Station } from "../../lib/stations";
import type { DurationIntent, HostMode } from "../../lib/types";
import { useOverlay } from "../../lib/overlay-stack";
import { CheckIcon, ChevronDownIcon, ClockIcon, MicIcon } from "../icons";

type Open = "duration" | "host" | null;

/** Gap kept between a menu and whatever it must not run into (the screen's edge, the navigation bar, the mini player). */
const EDGE_GAP = 8;
const MENU_GAP = 6;

/**
 * The two choices under the box: how long, and how much the host talks. Each opens a small menu under its chip
 * (not a sheet: it is one tap and one pick). The host chip shows the station's own default until the listener picks.
 */
export function TuneChoices({
  station,
  duration,
  onDuration,
  host,
  onHost,
}: {
  station: Station;
  duration: DurationIntent;
  onDuration: (value: DurationIntent) => void;
  /** What the control shows: the listener's pick, else the station's default. */
  host: HostMode;
  onHost: (value: HostMode) => void;
}) {
  const [open, setOpen] = useState<Open>(null);
  const [placement, setPlacement] = useState<{ side: "down" | "up"; maxHeight?: number }>({ side: "down" });
  const rootRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  useOverlay(open !== null, () => setOpen(null), { history: false });

  // A short page (a browser with its bars) leaves no room under the chips: open the menu upwards instead, and when
  // neither side has room for all of it, the roomier side with the menu scrolling. Measured before the first paint.
  useLayoutEffect(() => {
    if (!open) return;
    const menu = menuRef.current;
    const chip = rootRef.current?.querySelector<HTMLElement>('.tune-chip[aria-expanded="true"]');
    if (!menu || !chip) return;
    const rect = chip.getBoundingClientRect();
    const covers = [".bottom-nav", ".mini-player:not([hidden])"]
      .map((selector) => document.querySelector(selector)?.getBoundingClientRect().top)
      .filter((top): top is number => typeof top === "number" && top > 0);
    const floor = Math.min(window.innerHeight, ...covers) - EDGE_GAP;
    const below = floor - rect.bottom - MENU_GAP;
    const above = rect.top - MENU_GAP - EDGE_GAP;
    const height = menu.offsetHeight;
    const side = height <= below || below >= above ? "down" : "up";
    const room = side === "down" ? below : above;
    setPlacement({ side, maxHeight: height > room ? Math.max(120, room) : undefined });
  }, [open]);
  const toggle = (which: Exclude<Open, null>) => {
    // Always start below; the layout effect moves it if there is no room.
    setPlacement({ side: "down" });
    setOpen(open === which ? null : which);
  };
  const durationLabel = DURATION_CHIPS.find((chip) => chip.value === duration)?.label ?? DURATION_CHIPS[0].label;

  return (
    <div ref={rootRef} className="tune-chips" data-guide="tune-choices">
      <button
        type="button"
        className="tune-chip"
        aria-haspopup="menu"
        aria-expanded={open === "duration"}
        onClick={() => toggle("duration")}
      >
        <ClockIcon size={17} strokeWidth={1.9} />
        {durationLabel}
        <ChevronDownIcon size={13} strokeWidth={2.4} className="chip-caret" />
      </button>
      <button
        type="button"
        className="tune-chip"
        aria-haspopup="menu"
        aria-expanded={open === "host"}
        onClick={() => toggle("host")}
      >
        <MicIcon size={17} strokeWidth={1.9} />
        {hostChoiceLabel(host)}
        <ChevronDownIcon size={13} strokeWidth={2.4} className="chip-caret" />
      </button>

      {open ? <div className="chip-scrim" aria-hidden="true" onClick={() => setOpen(null)} /> : null}

      {open === "duration" ? (
        <div ref={menuRef} className="chip-menu chip-menu-duration" data-placement={placement.side}>
          <div role="menu" aria-label="时长" className="chip-menu-list" style={{ maxHeight: placement.maxHeight }}>
          {DURATION_CHIPS.map((chip) => (
            <button
              key={chip.value}
              type="button"
              role="menuitemradio"
              aria-checked={chip.value === duration}
              className="chip-item"
              onClick={() => {
                onDuration(chip.value);
                setOpen(null);
              }}
            >
              <span className="chip-item-text"><span className="chip-item-label">{chip.label}</span></span>
              <CheckIcon size={18} strokeWidth={2.4} className="chip-item-check" />
            </button>
          ))}
          </div>
        </div>
      ) : null}

      {open === "host" ? (
        <div ref={menuRef} className="chip-menu chip-menu-host" data-placement={placement.side}>
          <div role="menu" aria-label="主持" className="chip-menu-list" style={{ maxHeight: placement.maxHeight }}>
          {HOST_CHOICES.map((choice) => (
            <button
              key={choice.value}
              type="button"
              role="menuitemradio"
              aria-checked={choice.value === host}
              className="chip-item"
              onClick={() => {
                onHost(choice.value);
                setOpen(null);
              }}
            >
              <span className="chip-item-text">
                <span className="chip-item-label">
                  {choice.label}
                  {choice.value === station.host ? <span className="chip-item-tag">{station.name}默认</span> : null}
                </span>
                <span className="chip-item-hint">{choice.hint}</span>
              </span>
              <CheckIcon size={18} strokeWidth={2.4} className="chip-item-check" />
            </button>
          ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
