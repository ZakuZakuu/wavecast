import { beforeEach, describe, expect, it } from "vitest";

import { DURATION_CHIPS, DURATIONS, FIRST_VISIT_STATION_ID, HOST_CHOICES, hostChoiceLabel, hostToSend, matchStation, rememberProgrammeStation, STATIONS, stationById, stationForProgramme } from "../lib/stations";

describe("matchStation", () => {
  it("maps free text to stations by keyword", () => {
    expect(matchStation("方大同的故事")).toBe("portrait");
    expect(matchStation("UK Garage 是怎么来的")).toBe("lineage");
    expect(matchStation("睡前听点安静的")).toBe("night");
    expect(matchStation("推荐几首像 Frank Ocean 的歌")).toBe("crate");
    expect(matchStation("雨天开车")).toBe("casual");
    expect(matchStation("")).toBe("casual");
  });
});

describe("programme station memory", () => {
  beforeEach(() => window.localStorage.clear());

  it("prefers the remembered station over keyword matching", () => {
    expect(stationForProgramme("p1", "睡前").id).toBe("night");
    rememberProgrammeStation("p1", "crate");
    expect(stationForProgramme("p1", "睡前").id).toBe("crate");
  });
});

describe("the tuner's stations", () => {
  it("lands a first-time listener on 唱片行 and keeps 随便听 for an unknown id", () => {
    expect(FIRST_VISIT_STATION_ID).toBe("crate");
    expect(stationById(FIRST_VISIT_STATION_ID).name).toBe("唱片行");
    expect(stationById("nonsense").id).toBe("casual");
  });

  it("gives every station its colours, a one-liner and a hosting default that matches the backend", () => {
    const hosts = Object.fromEntries(STATIONS.map((station) => [station.id, station.host]));
    expect(hosts).toEqual({ casual: "LIGHT", crate: "LIGHT", portrait: "FULL", lineage: "FULL", night: "NONE" });
    for (const station of STATIONS) {
      for (const color of [station.light, station.deep, station.deepText, station.tint, station.tint2]) expect(color).toMatch(/^#[0-9A-Fa-f]{6}$/);
      expect(station.tagline.length).toBeGreaterThan(4);
    }
  });

  it("offers the two lengths as chips and three hosting levels in the backend's words", () => {
    expect(DURATION_CHIPS.map((chip) => chip.value)).toEqual(DURATIONS.map((tier) => tier.value));
    expect(DURATION_CHIPS.map((chip) => chip.label)).toEqual(["约 35 分钟", "约 1 小时"]);
    expect(HOST_CHOICES.map((choice) => choice.value)).toEqual(["NONE", "LIGHT", "FULL"]);
    expect(hostChoiceLabel("NONE")).toBe("只听歌");
    expect(hostChoiceLabel("FULL")).toBe("多讲解");
  });
});

describe("hostToSend", () => {
  it("sends the host control only when it differs from the station's own default", () => {
    const night = stationById("night");
    expect(hostToSend(null, night)).toBeNull();
    expect(hostToSend(night.host, night)).toBeNull();
    expect(hostToSend("FULL", night)).toBe("FULL");
    expect(hostToSend(night.host, stationById("portrait"))).toBe(night.host);
  });
});
