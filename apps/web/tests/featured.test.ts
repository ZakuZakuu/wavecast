import { describe, expect, it } from "vitest";

import { coverHeading, programmeCover } from "../lib/cover/programme-cover";
import {
  FEATURED_PORTRAIT_ARTIST,
  FEATURED_PROGRAMMES,
  featuredDurationIntent,
} from "../lib/featured";
import { STATIONS } from "../lib/stations";

describe("guest featured programmes", () => {
  it("has exactly one card per station, in station order", () => {
    expect(FEATURED_PROGRAMMES.map((item) => item.stationId)).toEqual(STATIONS.map((station) => station.id));
  });

  it("uses unique stable ids and non-empty copy", () => {
    const ids = new Set(FEATURED_PROGRAMMES.map((item) => item.id));
    expect(ids.size).toBe(FEATURED_PROGRAMMES.length);
    for (const item of FEATURED_PROGRAMMES) {
      expect(item.prompt.trim().length).toBeGreaterThanOrEqual(2);
      expect(item.title.trim()).not.toBe("");
      expect(item.minutes).toBeGreaterThan(0);
    }
  });

  it("derives the 人物志 prompt and title from the single artist setting", () => {
    const portrait = FEATURED_PROGRAMMES.find((item) => item.stationId === "portrait")!;
    expect(portrait.prompt).toBe(`${FEATURED_PORTRAIT_ARTIST}这些年的歌`);
    expect(portrait.title).toBe(FEATURED_PORTRAIT_ARTIST);
  });

  it("maps the estimate to the nearest duration intent", () => {
    const intents = FEATURED_PROGRAMMES.map(featuredDurationIntent);
    expect(intents[0]).toBe("SHORT");
    expect(featuredDurationIntent({ ...FEATURED_PROGRAMMES[0], minutes: 55 })).toBe("DEEP");
    expect(featuredDurationIntent({ ...FEATURED_PROGRAMMES[0], minutes: 28 })).toBe("STANDARD");
  });

  it("never cuts a title short on the cover", () => {
    for (const item of FEATURED_PROGRAMMES) {
      const heading = coverHeading(item.title);
      if (heading) expect(heading.replace(/\s+/g, "")).toBe(item.title.replace(/\s+/g, ""));
    }
  });

  it("draws the same cover every time, with the station's template", () => {
    for (const item of FEATURED_PROGRAMMES) {
      const first = programmeCover({ id: item.id, title: item.title, stationId: item.stationId });
      const again = programmeCover({ id: item.id, title: item.title, stationId: item.stationId });
      expect(again).toEqual(first);
      const station = STATIONS.find((candidate) => candidate.id === item.stationId)!;
      expect(station.templates).toContain(first.template);
    }
  });
});
