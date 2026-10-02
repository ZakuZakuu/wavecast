import { beforeEach, describe, expect, it } from "vitest";

import { matchStation, rememberProgrammeStation, stationForProgramme } from "../lib/stations";

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
