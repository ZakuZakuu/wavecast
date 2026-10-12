// Every piece of on-screen text in the demo film lives here. The current
// strings are the placeholder copy from the approved sample
// (docs/design/film/wavecast-film.html); swap in a real programme by editing
// this file only. Timing, motion and layout live in the composition.
//
// Station ids follow apps/web/lib/stations.ts. Cover seeds pick the
// procedural cover; changing a seed changes that cover's artwork.

import type { StationId } from "../../web/lib/stations";

export type Card = {
  station: StationId;
  /** Cover seed (any integer). */
  seed: number;
  /** Cover heading; "\n" breaks the line on the cover. */
  heading: string;
  title: string;
  /** Line under the title, usually "<station>，约 N 分钟". */
  meta: string;
};

export type RouteTrack = { name: string; state: "playing" | "queued" | "pending" };
export type RouteChapter = { at: string; title: string; status: string; tracks: RouteTrack[] };

export const content = {
  /** Eight captions, in order. "\n" breaks the line. */
  captions: [
    "每一档节目，\n都有自己的封面。",
    "拨一拨，\n换一个台。",
    "或者，\n直接说想听什么。",
    "几秒之后，\n音乐就响了。",
    "主持在间奏里说话，\n音乐自动让路。",
    "节目边播，\n边往前生成。",
    "整档节目，\n是一条路线。",
    "听过的，\n会变成下一次的推荐。",
  ],

  /** Mixer panel lane labels (35.6–43 s). */
  mixer: { music: "音乐", host: "主持" },

  ui: {
    homeTitle: "首页",
    avatar: "R",
    homeSection: "猜你想听",
    tabs: ["首页", "调频", "节目库"],
    tuneTitle: "调频",
    betweenStations: "两个台之间",
    betweenHint: "松手会自动对准最近的台",
    descChip: "按描述对准",
    inputPlaceholder: "说一个歌手、一首歌，或者你在做什么",
    durations: ["15 分钟", "半小时", "一小时"],
    /** CTA text; {freq} is replaced with the locked frequency. */
    ctaLocked: "在 FM {freq} 开播",
    ctaUnlocked: "先对准一个台",
    cancel: "取消",
    tuningFootnote: "音乐几秒内就会响起来，\n后面的内容边播边准备。",
    upNext: "接下来",
    hostSpeaking: "主持在说",
    fullText: "全文 ›",
    routeTitle: "节目路线",
  },

  /** Station strip labels and the line shown while locked on each station. */
  stations: {
    casual: "以音乐为主，主持偶尔说两句",
    crate: "从你喜欢的出发，挖你没听过的",
    portrait: "用一位歌手的作品，讲他走过的路",
    lineage: "一种风格是怎么来的",
    night: "几乎不说话，节奏放缓",
  } satisfies Record<StationId, string>,

  /** What the listener types on the tune screen (17.2–20.2 s). */
  prompt: "下雨天，想听点爵士钢琴",

  /** The programme that starts playing. */
  programme: {
    station: "night" as StationId,
    seed: 63,
    coverHeading: "下雨天的\n爵士钢琴",
    title: "下雨天的爵士钢琴",
    /** Shown as "约 32:00" under the progress bar and in the route sheet. */
    durationLabel: "约 32:00",
    routeSubtitle: "下雨天的爵士钢琴，约 32 分钟",
    /** Tuning-in checklist (25.6 / 27.2 / 28.8 s). */
    steps: ["听懂了：下雨天，想听点爵士钢琴", "开场歌就位：Bill Evans《Peace Piece》", "正在排后面的曲目"],
    nowPlaying: { title: "Peace Piece", artist: "Bill Evans" },
    upNext: { track: "Brad Mehldau《River Man》", chapter: "第 1 段：开场" },
    /** Host narration, scrolled line by line in the player (35.6–43 s). */
    host: ["注意听左手，", "它一直重复着同一个小节，", "右手在上面慢慢往前走。", "雨天听它，刚刚好。", "下一首，我们换一位钢琴手。"],
    route: [
      { at: "00:00", title: "开场", status: "正在播", tracks: [{ name: "Bill Evans《Peace Piece》", state: "playing" }, { name: "Brad Mehldau《River Man》", state: "queued" }] },
      { at: "09:20", title: "雨声里的钢琴", status: "已准备", tracks: [{ name: "坂本龙一《aqua》", state: "queued" }, { name: "Keith Jarrett《My Song》", state: "queued" }] },
      { at: "18:40", title: "换一种安静", status: "准备中", tracks: [{ name: "曲目待定", state: "pending" }] },
      { at: "27:30", title: "收尾", status: "准备中", tracks: [{ name: "曲目待定", state: "pending" }] },
    ] satisfies RouteChapter[],
  },

  /** Home grid at the start (four cards). */
  homeCards: [
    { station: "casual", seed: 11, heading: "下班路上", title: "下班路上听点轻松的：City Pop 与 Funk", meta: "随便听，约 30 分钟" },
    { station: "crate", seed: 27, heading: "City Pop\n之后", title: "听完 City Pop，再去找谁", meta: "唱片行，约 40 分钟" },
    { station: "portrait", seed: 43, heading: "坂本龙一\n这些年", title: "坂本龙一这些年的歌", meta: "人物志，约 45 分钟" },
    { station: "lineage", seed: 58, heading: "Bossa Nova\n怎么来的", title: "Bossa Nova 是怎么来的", meta: "来龙去脉，约 40 分钟" },
  ] satisfies Card[],

  /** Home grid after listening (four recommendation cards). */
  recommendations: {
    because: "因为你听了《下雨天的爵士钢琴》",
    cards: [
      { station: "lineage", seed: 71, heading: "钢琴三重奏\n入门", title: "钢琴三重奏入门：从 Bill Evans 开始", meta: "来龙去脉，约 40 分钟" },
      { station: "night", seed: 88, heading: "深夜的\nECM", title: "深夜的 ECM：安静的欧洲爵士", meta: "夜里，约 45 分钟" },
      { station: "casual", seed: 95, heading: "雨天的\nBossa Nova", title: "雨天的 Bossa Nova", meta: "随便听，约 30 分钟" },
      { station: "crate", seed: 104, heading: "Bill Evans\n之后", title: "Bill Evans 之后，还能听谁", meta: "唱片行，约 40 分钟" },
    ] satisfies Card[],
  },

  end: { name: "WaveCast", line: "说一句想听什么，电台马上开播。", url: "wavecast.space" },
};
