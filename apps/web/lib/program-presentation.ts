import type { Seed } from "./types";

export type ProgramPresentation = {
  genres: string;
  description: string;
  artists: string[];
  route: string[];
  mood: string;
};

const PRESENTATIONS: Record<string, Partial<ProgramPresentation>> = {
  "city-pop-misunderstood": {
    genres: "City Pop · Neo Soul · Late Night",
    description: "从城市夜色里的律动出发，听见 City Pop 如何跨过年代与海岸线，又在今天被重新理解。",
    artists: ["方大同", "Miki Matsubara", "Mariya Takeuchi", "Anri"],
    route: ["夜色渐入", "城市律动", "跨海回声", "慢慢收回来"],
    mood: "夜行 / 城市 / 温暖",
  },
  "synthpop-return": {
    genres: "Synthpop · Electronic · Night Drive",
    description: "从当代流行的合成器光泽往回走，找到 80s synthpop 那些明亮又有阴影的源头。",
    artists: ["The Weeknd", "A-ha", "New Order", "CHVRCHES"],
    route: ["当代入口", "霓虹鼓机", "80s 核心", "回到现在"],
    mood: "霓虹 / 夜驾 / 电子",
  },
};

export function programPresentation(seed: Seed): ProgramPresentation {
  const override = PRESENTATIONS[seed.id] ?? {};
  return {
    genres: override.genres ?? seed.topic,
    description: override.description ?? seed.short_description,
    artists: override.artists ?? (seed.opening_track_ref.startsWith("mock:") ? [] : [seed.opening_track_artist]),
    route: override.route ?? ["开场", "展开", "转折", "收尾"],
    mood: override.mood ?? seed.topic,
  };
}

export function durationLabel(seconds: number): string {
  return "约 " + Math.max(1, Math.round(seconds / 60)) + " 分钟";
}
