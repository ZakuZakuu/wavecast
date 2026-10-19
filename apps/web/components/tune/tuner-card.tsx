"use client";

import type { CSSProperties, Ref } from "react";

import { rgba } from "../../lib/cover/styled/color";
import { ChevronRightIcon, InfoIcon } from "../icons";
import { DialSlider } from "./dial-slider";
import { TunerFace } from "./tuner-face";
import type { Tuner } from "./use-tuner";

/**
 * The tuner card of the page: tint, words and picture of the station under the dial, the way to the 电台指南, the dial.
 * Tapping the picture or any bare part of the card opens the 电台指南 too (a swipe, which tunes, does not).
 */
export function TunerCard({ tuner, cardRef, onOpenGuide }: { tuner: Tuner; cardRef: Ref<HTMLElement>; onOpenGuide: () => void }) {
  const { station } = tuner;
  return (
    <section
      ref={cardRef}
      className="tuner-card"
      aria-label="调谐"
      style={{ "--card-shadow": rgba(station.light, 0.25), touchAction: "pan-y" } as CSSProperties}
      {...tuner.swipe}
      onClick={(event) => {
        // The link, the dial and its buttons do their own thing.
        if ((event.target as Element).closest("button, [data-tuner-dial]")) return;
        onOpenGuide();
      }}
    >
      <TunerFace freq={tuner.freq} />
      <button type="button" className="tuner-guide-link" data-guide="tune-guide-link" onClick={onOpenGuide}>
        <InfoIcon size={15} strokeWidth={2} />
        电台指南
        <ChevronRightIcon size={13} strokeWidth={2.4} />
      </button>
      <DialSlider
        freq={tuner.freq}
        reading={tuner.reading}
        station={station}
        dragging={tuner.dragging}
        wheelRef={tuner.dialRef}
        handlers={tuner.dial}
        onKeyDown={tuner.dial.onKeyDown}
        onStep={tuner.step}
        canStep={tuner.canStep}
        guide="tune-dial"
      />
    </section>
  );
}
