// Guest home "先听这几档": one hand-picked programme promise per station.
// Nothing is generated until a card is clicked (no proposal on page load).
import type { CoverPin } from "./cover/styled/types";
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
  /** Sent to the programme proposal endpoint on click. */
  prompt: string;
  /**
   * The title under the card and in the detail sheet, written the way the generator is told to
   * write titles (title_style.py): spoken, true to the request, no "A：B", nothing invented.
   */
  displayTitle: string;
  /** Short title drawn on the cover. */
  title: string;
  /** The cover is chosen by hand for these, so the home page always shows them at their best. */
  cover: CoverPin;
  /** Estimated length in minutes, shown on the card; maps to a duration intent. */
  minutes: number;
  /**
   * One sentence for the detail sheet: what the listener will be taken through. It describes the
   * mood or the route, never a catalogue or research promise the application cannot keep.
   */
  blurb: string;
};

export const FEATURED_PROGRAMMES: FeaturedProgramme[] = [
  {
    id: "featured-casual-commute",
    stationId: "casual",
    prompt: "下班路上听点轻松的",
    displayTitle: "下班路上，先慢半拍",
    title: "下班路上",
    cover: { style: "scene", motif: "road", layout: 2 },
    minutes: 35,
    blurb: "把一天的节奏放慢一点，一档不用费力去听的轻松歌曲。",
  },
  {
    id: "featured-crate-lofi",
    stationId: "crate",
    prompt: "喜欢 Lo-fi 的话，还能听什么",
    displayTitle: "喜欢 Lo-fi，还能听什么",
    title: "Lo-fi 之外",
    cover: { style: "sleeve", motif: "cassette", layout: 3 },
    minutes: 35,
    blurb: "喜欢 Lo-fi 的松弛感，接下来顺着它往外听，看看还有哪些相近的声音。",
  },
  {
    id: "featured-portrait-artist",
    stationId: "portrait",
    prompt: `${FEATURED_PORTRAIT_ARTIST}这些年的歌`,
    displayTitle: `${FEATURED_PORTRAIT_ARTIST}的几种声音`,
    title: FEATURED_PORTRAIT_ARTIST,
    cover: { style: "poster", motif: "keys", layout: 3 },
    minutes: 35,
    blurb: `沿着${FEATURED_PORTRAIT_ARTIST}的作品听一段，看他的音乐走过哪些地方。`,
  },
  {
    id: "featured-lineage-bossa-nova",
    stationId: "lineage",
    prompt: "Bossa Nova 是怎么来的",
    displayTitle: "Bossa Nova 是怎么来的",
    title: "Bossa Nova 的来历",
    cover: { style: "line", motif: "sea", layout: 4 },
    minutes: 35,
    blurb: "Bossa Nova 那种轻轻摇摆的节奏从哪里来？顺着它的来路听几首。",
  },
  {
    id: "featured-night-bedtime",
    stationId: "night",
    prompt: "睡前半小时，安静一点",
    displayTitle: "睡前半小时，慢慢静下来",
    title: "睡前半小时",
    cover: { style: "neon", motif: "moon", layout: 1 },
    minutes: 35,
    blurb: "睡前放慢下来的安静音乐，不抢你的注意力。",
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
