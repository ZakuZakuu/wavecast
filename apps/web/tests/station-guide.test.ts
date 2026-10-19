import { describe, expect, it } from "vitest";

import { hostLevel, STATION_GUIDES, stationExamples, stationPlaceholder } from "../lib/station-guide";
import { STATIONS } from "../lib/stations";
import { posterTransform, STATION_POSTERS } from "../lib/station-poster";

describe("the 电台指南 content", () => {
  it("has a page for every station with three things to write", () => {
    expect(Object.keys(STATION_GUIDES).sort()).toEqual(STATIONS.map((station) => station.id).sort());
    for (const guide of Object.values(STATION_GUIDES)) {
      expect(guide.scenes).toHaveLength(3);
      expect(guide.give.length).toBeGreaterThan(0);
      for (const scene of guide.scenes) {
        expect(scene.tag.length).toBeGreaterThanOrEqual(2);
        expect(scene.tag.length).toBeLessThanOrEqual(4);
        // What goes into the box is a sentence, not a template.
        expect(scene.text.length).toBeGreaterThanOrEqual(2);
        expect(scene.text.length).toBeLessThanOrEqual(30);
        expect(scene.text).not.toContain("\n");
        // A display break only moves the line break; the words are the same.
        if (scene.display) expect(scene.display.join("")).toBe(scene.text);
      }
    }
  });

  it("puts the jumpiest example of 随便听 last, so the first one a new listener sees is the safe one", () => {
    expect(STATION_GUIDES.casual.scenes.map((scene) => scene.tag)).toEqual(["有心情", "有场景", "想发现"]);
  });

  it("walks the examples of a station in order, and shows the first as the placeholder", () => {
    expect(stationExamples("crate")).toEqual(["我喜欢《旅行的意义》，挖几首类似的", "喜欢陈绮贞，还有谁", "只有吉他和人声的"]);
    expect(stationPlaceholder("crate")).toBe("我喜欢《旅行的意义》，\n挖几首类似的");
    expect(stationPlaceholder("portrait")).toBe("方大同这些年的作品");
  });

  it("shows how much the host talks as one to three bars", () => {
    expect([hostLevel("NONE"), hostLevel("LIGHT"), hostLevel("FULL")]).toEqual([1, 2, 3]);
  });
});

describe("the station posters", () => {
  it("has one picture per station, each cropped or inset so the corners cut nothing", () => {
    for (const station of STATIONS) {
      const spec = STATION_POSTERS[station.id];
      expect(spec.pin.layout).toBe(0);
      const { transform } = posterTransform(spec);
      expect(transform).toMatch(/scale\(/);
    }
    // The keys keep a margin all round.
    expect(STATION_POSTERS.portrait.scale).toBeLessThan(1);
    expect(posterTransform({ seed: 1, pin: STATION_POSTERS.casual.pin, crop: { scale: 2, cx: 0.5, cy: 0.5, px: 0.5, py: 0.5 } }).transform).toBe("translate(-50%, -50%) scale(2)");
  });
});
