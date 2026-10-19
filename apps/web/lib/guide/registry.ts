// First-use guides: a list of guides, each a few steps that light up a real element (`data-guide="…"`).
// To guide a new feature, add a guide here (and mark its element); people who have seen the others
// are shown only the new one. Rewording a guide that people should see again: raise its `version`.
export type GuideTrigger = "home" | "tune" | "library";

export type GuideStep = {
  /** `data-guide` value of the element to light up; none = a plain card over the dimmed screen. */
  target?: string;
  /** Where the card sits relative to the lit element (flips if there is no room). Default below. */
  side?: "above" | "below";
  title?: string;
  text: string;
  /** Button that goes on. Default 下一步, or 知道了 on the last step. */
  primary?: string;
  /** Label of the button that ends the guide early; false = none. Default 跳过. */
  skip?: string | false;
  /** The primary button ends the guide and goes here. */
  href?: string;
  /** Only for signed-in people or only for guests; default both. */
  audience?: "guest" | "member";
};

export type GuideDef = {
  id: string;
  version: number;
  trigger: GuideTrigger;
  /** Shown only after this guide has been seen (on a later visit: one guide per page view). */
  requires?: string;
  steps: GuideStep[];
};

export const GUIDES: readonly GuideDef[] = [
  {
    id: "home-intro",
    version: 1,
    trigger: "home",
    steps: [
      { title: "欢迎来到 WaveCast", text: "说出你想听的，我们为你编一档有故事的音乐电台。花半分钟，带你认一下路。", primary: "开始" },
      { target: "home-feature", audience: "guest", text: "点一档，就能开始听。先从这几档精选里挑一个。" },
      { target: "home-feature", audience: "member", text: "这是按你的口味准备的节目，点一档，就能开始听。" },
      { target: "home-stations", side: "above", text: "按电台风格调频。每个电台有自己的口味和节奏，点一下直达调频页。" },
      { target: "nav-tune", side: "above", text: "想听什么，直接说出来。歌手、歌曲，或者你正在做的事，都可以。" },
      {
        target: "home-picks-head",
        audience: "guest",
        title: "登录后，推荐更懂你",
        text: "登录后，这里会换成按你口味准备的节目，还能换一批、下拉刷新。",
        primary: "登录",
        skip: "以后再说",
        href: "/account",
      },
    ],
  },
  {
    id: "home-unlocked",
    version: 1,
    trigger: "home",
    requires: "home-intro",
    steps: [
      {
        target: "home-picks-head",
        audience: "member",
        title: "为你推荐已解锁",
        text: "这里按你的口味准备节目。点「换一批」，或把页面往下拉，都能换一批新的。",
        primary: "知道了",
        skip: false,
      },
    ],
  },
  {
    id: "tune-intro",
    version: 1,
    trigger: "tune",
    steps: [
      { target: "tune-dial", title: "先对准一个台", text: "左右拖动，对准一个电台。每个电台有自己的风格和节奏。" },
      { target: "tune-input", text: "想听什么，在这里说：一个歌手、一首歌，或者你在做什么。" },
      { target: "tune-duration", text: "选一档的长度：短节目 30–40 分钟，长节目约 1 小时。" },
      { target: "tune-onair", side: "above", text: "对准了就点开播。音乐几秒内响起，后面的内容边听边准备。" },
    ],
  },
  {
    id: "tune-full",
    version: 1,
    trigger: "tune",
    requires: "tune-intro",
    steps: [
      { target: "tune-prepare", side: "above", text: "想先备好、晚点再听？点这里准备完整版，做好后会留在节目库。", primary: "知道了", skip: false },
    ],
  },
  {
    id: "home-public",
    version: 1,
    trigger: "home",
    requires: "home-intro",
    steps: [
      { target: "home-public", text: "这是别人公开的整期节目，点一档就能直接听，不用等它生成。", primary: "知道了", skip: false },
    ],
  },
  {
    id: "library-marks",
    version: 1,
    trigger: "library",
    steps: [
      {
        target: "lib-marker",
        text: "灰色打钩的圆圈表示完整版，分享图标表示正在分享，分享的节目一定是完整版。",
        primary: "知道了",
        skip: false,
      },
    ],
  },
];
