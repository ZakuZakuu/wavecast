// Every piece of on-screen text in the film lives here (FILM_BRIEF.md §5).
// Programme titles, songs and host lines are illustrative, not real output.
import type { StationId } from "../../web/lib/stations";

export type Card = {
  station: StationId;
  seed: number;
  /** Short title drawn on the cover ("\n" = line break). */
  heading: string;
  /** Full title under the card. */
  title: string;
  meta: string;
};

export const BRAND = {
  name: "WaveCast",
  tagline: "一档为你现场编排的电台",
  endLine: "说一句想听什么，电台马上开播。",
  url: "wavecast.space",
  disclaimer: "概念演示，画面为示意，功能以实际产品为准",
};

/** Chapter cards and station calls (台呼), one per moment. */
export const CHAPTERS = {
  morning: { time: "07:40", freq: "FM 88.7", station: "随便听", call: "早上好，这里是 FM 88.7，随便听。" },
  afternoon: { time: "14:20", freq: "FM 93.1", station: "唱片行", call: "下午好，FM 93.1，唱片行。" },
  night: { time: "22:30", freq: "FM 105.8", station: "夜里", call: "晚上好，这里是 FM 105.8，夜里。" },
  nextMorning: { time: "次日 07:30", freq: null, station: null, call: "早上好，今天想听点什么？" },
} as const;

/** Left-hand product lines; each is two short lines. */
export const LINES = {
  morning: [
    ["每一档节目，", "都有自己的封面。"],
    ["早上，", "点一下就开播。"],
  ],
  afternoon: [
    ["说一句想听什么。"],
    ["后台把一档节目，", "现场编排出来。"],
  ],
  night: [
    ["主持在间奏里说话，", "音乐自动让路。"],
    ["节目边播，", "边往前生成。"],
    ["整档节目，", "是一条路线。"],
  ],
  nextMorning: [["听过的，", "会变成下一次的推荐。"]],
};

/** Home "猜你想听" in the morning; the first card is the one tapped. */
export const HOME_CARDS: Card[] = [
  { station: "casual", seed: 11, heading: "通勤路上", title: "通勤路上：City Pop 与 Funk", meta: "随便听，约 30 分钟" },
  { station: "crate", seed: 27, heading: "City Pop\n之后", title: "听完 City Pop，再去找谁", meta: "唱片行，约 40 分钟" },
  { station: "portrait", seed: 43, heading: "坂本龙一\n这些年", title: "坂本龙一这些年的歌", meta: "人物志，约 45 分钟" },
  { station: "lineage", seed: 58, heading: "Bossa Nova\n怎么来的", title: "Bossa Nova 是怎么来的", meta: "来龙去脉，约 40 分钟" },
];

/** Next-morning recommendations. */
export const RECO = {
  why: "因为你昨晚听了《下雨天的爵士钢琴》",
  cards: [
    { station: "lineage", seed: 71, heading: "钢琴三重奏\n入门", title: "钢琴三重奏入门：从 Bill Evans 开始", meta: "来龙去脉，约 40 分钟" },
    { station: "night", seed: 88, heading: "深夜的\nECM", title: "深夜的 ECM：安静的欧洲爵士", meta: "夜里，约 45 分钟" },
    { station: "casual", seed: 95, heading: "雨天的\nBossa Nova", title: "雨天的 Bossa Nova", meta: "随便听，约 30 分钟" },
    { station: "crate", seed: 104, heading: "Bill Evans\n之后", title: "Bill Evans 之后，还能听谁", meta: "唱片行，约 40 分钟" },
  ] as Card[],
};

export type Programme = {
  station: StationId;
  seed: number;
  heading: string;
  song: string;
  artist: string;
  next: string;
  nextChapter: string;
  /** Elapsed and total on the progress bar. */
  elapsed: number;
  total: string;
};

export const PROGRAMMES: Record<"morning" | "afternoon" | "night", Programme> = {
  morning: {
    station: "casual",
    seed: 11,
    heading: "通勤路上",
    song: "Plastic Love",
    artist: "竹内玛莉亚",
    next: "山下达郎《Sparkle》",
    nextChapter: "第 1 段：开场",
    elapsed: 42,
    total: "约 30:00",
  },
  afternoon: {
    station: "crate",
    seed: 131,
    heading: "Nujabes\n之后",
    song: "Aruarian Dance",
    artist: "Nujabes",
    next: "Fat Jon《Your Purpose》",
    nextChapter: "第 1 段：开场",
    elapsed: 18,
    total: "约 40:00",
  },
  night: {
    station: "night",
    seed: 63,
    heading: "下雨天的\n爵士钢琴",
    song: "Peace Piece",
    artist: "Bill Evans",
    next: "Brad Mehldau《River Man》",
    nextChapter: "第 1 段：开场",
    elapsed: 228,
    total: "约 32:00",
  },
};

/** Afternoon tuner: what gets typed. */
export const TYPED = "想找点和 Nujabes 类似的";
export const TUNE = {
  title: "调频",
  placeholder: "说一个歌手、一首歌，或者你在做什么",
  between: "两个台之间",
  betweenHint: "松手会自动对准最近的台",
  matched: "按描述对准",
  ctaLocked: (freq: string) => `在 FM ${freq} 开播`,
  ctaBetween: "先对准一个台",
  durations: ["15 分钟", "半小时", "一小时"],
  tuningHint: ["音乐几秒内就会响起来，", "后面的内容边播边准备。"],
  cancel: "取消",
};

/** Behind-the-scenes cards (幕后拆解). `visual` cards carry an animation instead of a body line. */
export const BREAKDOWN: Array<{ title: string; body?: string; visual?: "voice" | "mix" }> = [
  { title: "理解主题", body: "想找和 Nujabes 气质相近的歌" },
  { title: "检索资料", body: "爵士采样、日本爵士嘻哈、Lo-fi 的源头" },
  { title: "规划路线", body: "从熟悉的出发，往外走两步，再收回来" },
  { title: "写主持词", body: "“这首的鼓是从一张老爵士唱片里采来的。”" },
  { title: "合成语音", visual: "voice" },
  { title: "混音", visual: "mix" },
];

/** Night host lines, shown as film subtitles and in the phone's status strip. */
export const HOST = ["注意听左手，", "它一直重复着同一个小节，", "右手在上面慢慢往前走。", "雨天听它，刚刚好。", "下一首，我们换一位钢琴手。"];

export const PLAYER = { upNext: "接下来", hostSpeaking: "主持在说", fullText: "全文 ›" };
export const MIXER = { music: "音乐", host: "主持" };

export const ROUTE = {
  title: "节目路线",
  sub: "下雨天的爵士钢琴，约 32 分钟",
  chapters: [
    { at: "00:00", title: "开场", state: "正在播", tracks: [["Bill Evans《Peace Piece》", 1], ["Brad Mehldau《River Man》", 0]] as Array<[string, number]> },
    { at: "09:20", title: "雨声里的钢琴", state: "已准备", tracks: [["坂本龙一《aqua》", 0], ["Keith Jarrett《My Song》", 0]] as Array<[string, number]> },
    { at: "18:40", title: "换一种安静", state: "准备中", tracks: [["曲目待定", 2]] as Array<[string, number]> },
    { at: "27:30", title: "收尾", state: "准备中", tracks: [["曲目待定", 2]] as Array<[string, number]> },
  ],
};

export const HOME = { title: "首页", picks: "猜你想听", avatar: "R", tabs: ["首页", "调频", "节目库"] };

/**
 * Cover wall short titles: the film's own headings plus existing product
 * titles, mixed with new ones (≤ 6 CJK wide, plain wording, all five stations).
 */
export const WALL_TITLES: Array<[StationId, string]> = [
  // already in the film / prototype / apps/web
  ["casual", "通勤路上"],
  ["crate", "City Pop\n之后"],
  ["portrait", "坂本龙一\n这些年"],
  ["lineage", "Bossa Nova\n怎么来的"],
  ["lineage", "钢琴三重奏\n入门"],
  ["night", "深夜的\nECM"],
  ["casual", "雨天的\nBossa Nova"],
  ["crate", "Bill Evans\n之后"],
  ["night", "下雨天的\n爵士钢琴"],
  ["crate", "Nujabes\n之后"],
  ["casual", "下班路上"],
  ["crate", "Lo-fi\n之外"],
  ["night", "睡前半小时"],
  ["casual", "雨天开车"],
  ["crate", "从方大同\n往外听"],
  ["lineage", "UK Garage\n怎么来的"],
  // new
  ["casual", "周末早餐"],
  ["casual", "午饭后"],
  ["casual", "开车去海边"],
  ["casual", "做饭的时候"],
  ["casual", "跑步听的"],
  ["casual", "下午犯困"],
  ["casual", "洗衣服时"],
  ["crate", "冷门 B 面"],
  ["crate", "老唱片采样"],
  ["crate", "日本爵士"],
  ["crate", "灵魂乐采样"],
  ["crate", "爵士嘻哈"],
  ["crate", "城市民谣"],
  ["portrait", "李宗盛的歌"],
  ["portrait", "王菲早期"],
  ["portrait", "久石让"],
  ["portrait", "罗大佑"],
  ["portrait", "陈绮贞"],
  ["portrait", "宇多田光"],
  ["lineage", "迪斯科简史"],
  ["lineage", "Funk\n从哪来"],
  ["lineage", "布鲁斯源头"],
  ["lineage", "雷鬼的来历"],
  ["lineage", "电子乐起点"],
  ["lineage", "华语摇滚"],
  ["night", "失眠的时候"],
  ["night", "凌晨三点"],
  ["night", "安静的钢琴"],
  ["night", "读书时听"],
  ["night", "下雨的夜里"],
];
