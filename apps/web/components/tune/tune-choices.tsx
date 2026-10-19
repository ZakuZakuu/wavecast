"use client";

import { useState } from "react";

import { DURATION_CHIPS, HOST_CHOICES, hostChoiceLabel, type Station } from "../../lib/stations";
import type { DurationIntent, HostMode } from "../../lib/types";
import { useOverlay } from "../../lib/overlay-stack";
import { CheckIcon, ChevronDownIcon, ClockIcon, MicIcon } from "../icons";

type Open = "duration" | "host" | null;

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
  useOverlay(open !== null, () => setOpen(null), { history: false });
  const durationLabel = DURATION_CHIPS.find((chip) => chip.value === duration)?.label ?? DURATION_CHIPS[0].label;

  return (
    <div className="tune-chips" data-guide="tune-choices">
      <button
        type="button"
        className="tune-chip"
        aria-haspopup="menu"
        aria-expanded={open === "duration"}
        onClick={() => setOpen(open === "duration" ? null : "duration")}
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
        onClick={() => setOpen(open === "host" ? null : "host")}
      >
        <MicIcon size={17} strokeWidth={1.9} />
        {hostChoiceLabel(host)}
        <ChevronDownIcon size={13} strokeWidth={2.4} className="chip-caret" />
      </button>

      {open ? <div className="chip-scrim" aria-hidden="true" onClick={() => setOpen(null)} /> : null}

      {open === "duration" ? (
        <div role="menu" aria-label="时长" className="chip-menu chip-menu-duration">
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
      ) : null}

      {open === "host" ? (
        <div role="menu" aria-label="主持" className="chip-menu chip-menu-host">
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
      ) : null}
    </div>
  );
}
