// The film's clock. All times are seconds from the first frame and follow the
// storyboard in docs/design/film/FILM_BRIEF.md §3. Sound effects and the music
// cue sheet are derived from the same numbers.
export const FPS = 30;
export const DURATION = 128;
export const WIDTH = 1920;
export const HEIGHT = 1080;

export const SEG = {
  cold: [0, 9],
  morning: [9, 33],
  afternoon: [33, 65],
  night: [65, 100],
  nextMorning: [100, 117],
  end: [117, 128],
} as const;

export const COLD = {
  dialIn: [0.4, 1.2],
  sweep: [1.0, 6.0],
  lock: [6.0, 6.6],
  brandIn: 6.4,
  dialOut: [6.4, 7.2],
  brandOut: 7.6,
  dawn: [8.2, 9.0],
  /** Noise bed. */
  static: [0.4, 6.6],
  startFreq: 107,
  lockFreq: 88.7,
};

/** Chapter card + station call start for each moment. Call lasts CALL_HOLD, then the card shrinks. */
export const CHAPTER_AT = { morning: 9.3, afternoon: 33.5, night: 65.6, nextMorning: 100.6 };
export const CALL_HOLD = 3.5;
/** Mini chapter marker fades out before the next moment / cover wall. */
export const CHAPTER_OUT = { morning: 32.2, afternoon: 63.6, night: 98.6, nextMorning: 110.0 };

export const MORNING = {
  phoneIn: [9.2, 10.4],
  coversAt: 10.2,
  coverStagger: 0.6,
  coverBuild: 2.0,
  line1: [13.6, 18.0],
  tap: [17.4, 18.1],
  open: [18.0, 18.9],
  line2: [19.2, 25.4],
  collapseDrag: [24.6, 25.6],
  collapse: [25.0, 25.8],
  scrollSwipe: [26.6, 27.8],
  scroll: [26.8, 27.9],
  tabTap: [31.6, 32.2],
};

export const AFTERNOON = {
  light: [32.4, 33.6],
  tuneIn: [32.1, 32.6],
  pushIn: [36.6, 37.4],
  drag: [37.6, 40.8],
  pushOut: [41.0, 41.8],
  line1: [41.4, 46.6],
  typing: [41.9, 44.1],
  align: [44.4, 45.4],
  chip: 45.2,
  ctaTap: [45.7, 46.3],
  tuningIn: 46.3,
  breakdown: [47.3, 58.2],
  explode: [47.3, 48.5],
  cardsLit: 48.7,
  cardStep: 1.3,
  collapse: [56.6, 57.8],
  line2: [48.6, 57.0],
  player: 57.8,
  phoneOut: [63.2, 64.2],
};

export const NIGHT = {
  light: [63.6, 64.8],
  rainIn: [63.8, 65.6],
  phoneIn: [65.4, 66.8],
  host: [70.4, 79.4],
  hostLine: 1.8,
  line1: [70.0, 79.4],
  mixer: [70.2, 79.6],
  pushIn: [80.0, 80.8],
  progress: [80.6, 85.4],
  line2: [80.4, 85.6],
  pushOut: [85.6, 86.4],
  routeTap: [86.2, 86.8],
  route: [86.8, 94.0],
  line3: [86.6, 93.6],
  rainOut: [97.4, 100.2],
  light2: [98.0, 100.4],
  collapse: [97.6, 98.6],
};

export const NEXT = {
  coversAt: 101.6,
  coverStagger: 0.6,
  coverBuild: 2.0,
  why: 101.2,
  line1: [104.6, 109.6],
  wall: [110.2, 116.8],
  pullBack: [110.2, 111.4],
};

export const END = {
  gather: [117.0, 119.6],
  icon: 118.8,
  name: 119.8,
  line: 120.4,
  url: 121.0,
  fade: [127.0, 128.0],
};
