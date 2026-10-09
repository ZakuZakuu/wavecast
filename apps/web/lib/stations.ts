// Station catalogue (HANDOFF §4.1). P0 lives in the frontend; P1 moves it to the backend.
import type { DurationIntent } from "./types";

export type StationId = "casual" | "crate" | "portrait" | "lineage" | "night";
export type CoverTemplate = "column" | "label" | "freq" | "horizon" | "contour" | "split";

export type Station = {
  id: StationId;
  name: string;
  freq: number;
  /** Light colour: station dot, background glow. */
  light: string;
  /** Deep colour: home station card background (white text). */
  deep: string;
  line: string;
  description: string;
  defaultTopic: string;
  /** Cover v2 (Cover2.dc.html): three templates, picked by the programme seed. */
  templates: CoverTemplate[];
  /** Palette hue and the odds of the dark mode (light/vivid split the rest). */
  cover: { hue: number; dark: number };
};

export const STATIONS: Station[] = [
  {
    id: "casual",
    name: "随便听",
    freq: 88.7,
    light: "#E8834A",
    deep: "#B5562A",
    line: "音乐为主，偶尔说两句",
    description: "以音乐为主，主持偶尔说两句。像开车时听的电台。",
    defaultTopic: "随便放点好听的",
    templates: ["freq", "split", "horizon"],
    cover: { hue: 22, dark: 0.25 },
  },
  {
    id: "crate",
    name: "唱片行",
    freq: 93.1,
    light: "#3E9C8C",
    deep: "#2E7D70",
    line: "挖你没听过的",
    description: "从一首你喜欢的歌出发，往外挖你还没听过的。",
    defaultTopic: "挖几首我可能没听过的好歌",
    templates: ["label", "split", "contour"],
    cover: { hue: 168, dark: 0.45 },
  },
  {
    id: "portrait",
    name: "人物志",
    freq: 97.4,
    light: "#C9A04A",
    deep: "#8F6B25",
    line: "一位歌手的路",
    description: "用一位歌手的作品，讲他走过的路。",
    defaultTopic: "讲一位华语歌手这些年的作品",
    templates: ["column", "label", "split"],
    cover: { hue: 38, dark: 0.35 },
  },
  {
    id: "lineage",
    name: "来龙去脉",
    freq: 101.5,
    light: "#5C7CE0",
    deep: "#3F5FC4",
    line: "一种风格的来历",
    description: "一种风格是怎么来的，跨年代串起来听。",
    defaultTopic: "City Pop 是怎么来的",
    templates: ["contour", "column", "freq"],
    cover: { hue: 224, dark: 0.4 },
  },
  {
    id: "night",
    name: "夜里",
    freq: 105.8,
    light: "#6E62B6",
    deep: "#5A4FA0",
    line: "几乎不说话",
    description: "几乎不说话，节奏放缓。适合睡前和专注。",
    defaultTopic: "睡前听的安静音乐",
    templates: ["horizon", "contour", "split"],
    cover: { hue: 252, dark: 0.8 },
  },
];

export const DEFAULT_STATION_ID: StationId = "casual";
export const FREQ_MIN = 87.5;
export const FREQ_MAX = 108;

export function stationById(id: string | null | undefined): Station {
  return STATIONS.find((station) => station.id === id) ?? STATIONS[0];
}

export function formatFreq(freq: number): string {
  return freq.toFixed(1);
}

/**
 * Two tiers, both "about": the programme ends on the track nearest the target, so the real
 * length can differ by several minutes and the labels never promise an exact one.
 * (STANDARD is the former middle tier; the backend treats it as the short one.)
 */
export const DURATIONS: Array<{ label: string; value: DurationIntent; minutes: number }> = [
  { label: "短节目 · 30–40 分钟", value: "SHORT", minutes: 35 },
  { label: "长节目 · 约 1 小时", value: "DEEP", minutes: 60 },
];

const RULES: Array<{ station: StationId; patterns: RegExp[] }> = [
  { station: "portrait", patterns: [/的故事/, /这些年/, /生平/, /是谁/, /一位歌手/, /这个人/] },
  { station: "lineage", patterns: [/怎么来的/, /历史/, /年代/, /起源/, /来历/, /演变/, /发展/] },
  { station: "night", patterns: [/睡/, /夜/, /专注/, /安静/, /学习/, /助眠/, /冥想/] },
  { station: "crate", patterns: [/像/, /类似/, /推荐/, /没听过/, /挖/, /冷门/] },
];

/**
 * P0 keyword matcher from free text to a station (HANDOFF §6.1). Order matters:
 * the first matching rule wins; anything else is 随便听.
 */
export function matchStation(text: string): StationId {
  const normalized = text.trim();
  if (!normalized) return DEFAULT_STATION_ID;
  for (const rule of RULES) {
    if (rule.patterns.some((pattern) => pattern.test(normalized))) return rule.station;
  }
  return DEFAULT_STATION_ID;
}

// --- Local station ownership for programmes (P1 will return it from the backend).

const STATION_MAP_KEY = "wavecast-programme-stations-v1";

function readStationMap(): Record<string, StationId> {
  if (typeof window === "undefined") return {};
  try {
    const parsed = JSON.parse(window.localStorage.getItem(STATION_MAP_KEY) ?? "{}");
    return parsed && typeof parsed === "object" ? parsed as Record<string, StationId> : {};
  } catch {
    return {};
  }
}

export function rememberProgrammeStation(programmeId: string, stationId: StationId): void {
  if (typeof window === "undefined") return;
  try {
    const map = readStationMap();
    map[programmeId] = stationId;
    const entries = Object.entries(map).slice(-200);
    window.localStorage.setItem(STATION_MAP_KEY, JSON.stringify(Object.fromEntries(entries)));
  } catch {
    // Storage is a convenience; matching still works without it.
  }
}

/** Remembered station for a programme, else a keyword match on its copy. */
export function stationForProgramme(programmeId: string, ...copy: Array<string | null | undefined>): Station {
  const remembered = readStationMap()[programmeId];
  if (remembered) return stationById(remembered);
  return stationById(matchStation(copy.filter(Boolean).join(" ")));
}
