// What the 电台指南 tells a first-time listener about each station: what to give it, what it does,
// and three things to write. Each sentence was run against the real proposal stage (a fitting opening
// track and programme direction came back). Reword with care: a scene that no longer yields a fitting
// programme is worse than none.
import type { HostMode } from "./types";
import type { StationId } from "./stations";

export type StationScene = {
  /** Two to four characters: which kind of thing this is. */
  tag: string;
  /** What goes into the input box when the scene is tapped. */
  text: string;
  /** The same text broken where it reads best on the card (a line break in the middle). */
  display?: readonly [string, string];
};

export type StationGuide = {
  /** What the listener can tell this station, one item per line ("一种心情", "一个场景"). */
  give: readonly string[];
  /** The station's job, two lines. */
  positioning: readonly [string, string];
  scenes: readonly [StationScene, StationScene, StationScene];
};

export const STATION_GUIDES: Record<StationId, StationGuide> = {
  casual: {
    give: ["一种心情", "一个场景"],
    positioning: ["替你挑歌，偶尔说两句。", "想放松或想换口味，都交给它。"],
    scenes: [
      { tag: "有心情", text: "下雨天，有点想家" },
      { tag: "有场景", text: "周五下班路上" },
      // Last on purpose: it jumps further from a listener who has no taste on record yet.
      { tag: "想发现", text: "来点我平时不会听的歌" },
    ],
  },
  crate: {
    give: ["一首喜欢的歌"],
    positioning: ["从一首喜欢的歌往外挖，", "告诉你为什么值得听。"],
    scenes: [
      { tag: "一首歌", text: "我喜欢《旅行的意义》，挖几首类似的", display: ["我喜欢《旅行的意义》，", "挖几首类似的"] },
      { tag: "一位歌手", text: "喜欢陈绮贞，还有谁" },
      { tag: "一种听感", text: "只有吉他和人声的" },
    ],
  },
  portrait: {
    give: ["一位歌手"],
    positioning: ["用作品讲一个人走过的路，", "主持讲得比较多。"],
    scenes: [
      { tag: "整体", text: "方大同这些年的作品" },
      { tag: "一个角度", text: "陈奕迅的情歌是怎么变的" },
      { tag: "刚认识", text: "刚听到椎名林檎，想了解她" },
    ],
  },
  lineage: {
    give: ["一种风格", "一个问题"],
    positioning: ["把一种风格的来龙去脉", "跨年代串起来讲，说得最多。"],
    scenes: [
      { tag: "起源", text: "Bossa Nova 是怎么传到世界的", display: ["Bossa Nova 是怎么", "传到世界的"] },
      { tag: "又火了", text: "City Pop 为什么又火了" },
      { tag: "影响", text: "合成器怎么改变了流行音乐" },
    ],
  },
  night: {
    give: ["一个想安静的时候"],
    positioning: ["几乎不说话，节奏放慢，", "适合睡前和专注。"],
    scenes: [
      { tag: "睡前", text: "睡前听，几首安静的钢琴曲" },
      { tag: "专注", text: "写东西时的背景音乐，别有歌词", display: ["写东西时的背景音乐，", "别有歌词"] },
      { tag: "夜路", text: "夜里开车，不要太吵" },
    ],
  },
};

/** Three bars: how much the host talks by default. */
export function hostLevel(host: HostMode): 1 | 2 | 3 {
  return host === "NONE" ? 1 : host === "LIGHT" ? 2 : 3;
}

/** The sample sentences the input box offers, in the order its shuffle button walks them. */
export function stationExamples(id: StationId): string[] {
  return STATION_GUIDES[id].scenes.map((scene) => scene.text);
}

/** The grey example in the empty box: the first scene, broken where it reads best. */
export function stationPlaceholder(id: StationId): string {
  const scene = STATION_GUIDES[id].scenes[0];
  return scene.display ? `${scene.display[0]}\n${scene.display[1]}` : scene.text;
}
