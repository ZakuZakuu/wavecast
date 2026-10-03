// Guest home "先听这几档": one hand-picked programme promise per station.
// Nothing is generated until a card is clicked (no proposal on page load).
import { DURATIONS, type StationId } from "./stations";
import type { DurationIntent } from "./types";

/**
 * The 人物志 artist is provisional and may change with the catalogue.
 * Change it here only; the prompt and card title follow.
 */
export const FEATURED_PORTRAIT_ARTIST = "坂本龙一";

export type FeaturedProgramme = {
  /** Stable id: seeds the procedural cover so it never changes between visits. */
  id: string;
  stationId: StationId;
  /** Sent to the programme proposal endpoint on click; also the full title under the card. */
  prompt: string;
  /** Short title drawn on the cover. */
  title: string;
  /** Estimated length in minutes, shown on the card; maps to a duration intent. */
  minutes: number;
};

export const FEATURED_PROGRAMMES: FeaturedProgramme[] = [
  {
    id: "featured-casual-commute",
    stationId: "casual",
    prompt: "下班路上听点轻松的",
    title: "下班路上",
    minutes: 15,
  },
  {
    id: "featured-crate-lofi",
    stationId: "crate",
    prompt: "喜欢 Lo-fi 的话，还能听什么",
    title: "Lo-fi 之外",
    minutes: 30,
  },
  {
    id: "featured-portrait-artist",
    stationId: "portrait",
    prompt: `${FEATURED_PORTRAIT_ARTIST}这些年的歌`,
    title: FEATURED_PORTRAIT_ARTIST,
    minutes: 30,
  },
  {
    id: "featured-lineage-bossa-nova",
    stationId: "lineage",
    prompt: "Bossa Nova 是怎么来的",
    title: "Bossa Nova 的来历",
    minutes: 30,
  },
  {
    id: "featured-night-bedtime",
    stationId: "night",
    prompt: "睡前半小时，安静一点",
    title: "睡前半小时",
    minutes: 30,
  },
];

/** The proposal duration intent closest to the card's estimate. */
export function featuredDurationIntent(item: FeaturedProgramme): DurationIntent {
  let best = DURATIONS[0];
  for (const option of DURATIONS) {
    if (Math.abs(option.minutes - item.minutes) < Math.abs(best.minutes - item.minutes)) best = option;
  }
  return best.value;
}
