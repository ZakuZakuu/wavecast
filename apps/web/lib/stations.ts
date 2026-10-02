// Station catalogue (HANDOFF §4.1). P0 lives in the frontend; P1 moves it to the backend.
import type { DurationIntent } from "./types";

export type StationId = "casual" | "crate" | "portrait" | "lineage" | "night";
export type CoverTemplate = "column" | "label" | "freq" | "horizon" | "contour" | "split";
export type CoverPalette = { bg: string; p1: string; p2: string; ink: string };

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
  templates: CoverTemplate[];
  palettes: Partial<Record<CoverTemplate, CoverPalette>>;
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
    templates: ["freq", "split"],
    palettes: {
      freq: { bg: "#F2C9A8", p1: "#B4542A", p2: "#FFFFFF", ink: "#3A1E10" },
      split: { bg: "#ECEFEC", p1: "#3E9C8C", p2: "#E8834A", ink: "#12302C" },
    },
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
    templates: ["label"],
    palettes: { label: { bg: "#173B36", p1: "#6FB5A6", p2: "#F0D9A6", ink: "#173B36" } },
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
    templates: ["column"],
    palettes: { column: { bg: "#F1E9D8", p1: "#B0823A", p2: "#2E2A24", ink: "#2E2A24" } },
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
    templates: ["contour"],
    palettes: { contour: { bg: "#E4E9F5", p1: "#5C7CE0", p2: "#1F2A4D", ink: "#1F2A4D" } },
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
    templates: ["horizon"],
    palettes: { horizon: { bg: "#1E1B3A", p1: "#6E62B6", p2: "#F3B8A0", ink: "#E9E6FF" } },
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

export const DURATIONS: Array<{ label: string; value: DurationIntent; minutes: number }> = [
  { label: "15 分钟", value: "SHORT", minutes: 15 },
  { label: "半小时", value: "STANDARD", minutes: 30 },
  { label: "一小时", value: "DEEP", minutes: 60 },
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
