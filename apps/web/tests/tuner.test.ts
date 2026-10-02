import { describe, expect, it } from "vitest";

import { STATIONS } from "../lib/stations";
import { clampFreq, freqAfterDrag, freqToX, knurlXs, nearestStation, PX_PER_MHZ, readTuner, snapTarget, stepStation, tickGeometry } from "../lib/tuner";

describe("scale conversion", () => {
  it("maps 38.75px to 1 MHz around the centred pointer", () => {
    expect(PX_PER_MHZ).toBe(38.75);
    expect(freqToX(97.4, 97.4, 310)).toBe(155);
    expect(freqToX(98.4, 97.4, 310)).toBeCloseTo(193.75);
    expect(freqAfterDrag(97.4, 38.75)).toBeCloseTo(96.4);
    expect(freqAfterDrag(97.4, -77.5)).toBeCloseTo(99.4);
  });

  it("clamps to 87.5–108", () => {
    expect(clampFreq(80)).toBe(87.5);
    expect(clampFreq(120)).toBe(108);
    expect(freqAfterDrag(88, 1000)).toBe(87.5);
  });

  it("draws a 0.2 MHz scale with integer / half / minor heights", () => {
    const ticks = tickGeometry(97.4, 310);
    // Window shows about 8 MHz; numbers on even integers only.
    expect(ticks.numbers.map((n) => n.label)).toEqual(["94", "96", "98", "100"]);
    expect(ticks.major).toContain("V52");
    // On a 0.2 MHz grid x.5 never occurs, so (as in the design source) minor ticks are all 7px.
    const heights = new Set([...ticks.minor.matchAll(/M[\d.]+ ([\d.]+)V52/g)].map((m) => 52 - Number(m[1])));
    expect([...heights]).toEqual([7]);
    expect(new Set([...ticks.major.matchAll(/M[\d.]+ ([\d.]+)V52/g)].map((m) => 52 - Number(m[1])))).toEqual(new Set([18]));
  });
});

describe("snapping and states", () => {
  it("always settles on the nearest station, honouring fling velocity", () => {
    expect(snapTarget(95.2)).toBe(93.1);
    expect(snapTarget(95.4)).toBe(97.4);
    expect(snapTarget(95.2, 0.01)).toBe(97.4);
    expect(STATIONS.map((s) => s.freq)).toContain(snapTarget(108));
  });

  it("locks within ±0.15 and is between stations beyond 0.3", () => {
    expect(readTuner(97.5)).toMatchObject({ locked: true, between: false, bars: 5 });
    expect(readTuner(97.65)).toMatchObject({ locked: false, between: false, bars: 3 });
    expect(readTuner(95.2)).toMatchObject({ locked: false, between: true, bars: 1 });
    expect(readTuner(95.2).noise).toBeGreaterThan(readTuner(97.8).noise);
    expect(nearestStation(104).station.name).toBe("夜里");
  });

  it("steps between stations with the keyboard", () => {
    expect(stepStation(97.4, 1).name).toBe("来龙去脉");
    expect(stepStation(97.4, -1).name).toBe("唱片行");
    expect(stepStation(88.7, -1).name).toBe("随便听");
    expect(stepStation(95.2, 1).name).toBe("人物志");
  });
});

describe("knurled dial", () => {
  it("has 31 grooves within ±70° and never packs them closer than 4px", () => {
    for (const phase of [0, 0.01, 0.03, 0.05]) {
      const xs = knurlXs(310, phase);
      expect(xs.length).toBeGreaterThanOrEqual(30);
      expect(xs.length).toBeLessThanOrEqual(31);
      for (let i = 1; i < xs.length; i += 1) expect(xs[i] - xs[i - 1]).toBeGreaterThanOrEqual(4);
    }
    expect(knurlXs(310, 0)).toHaveLength(31);
  });

  it("moves the grooves as the phase changes", () => {
    expect(knurlXs(310, 0.02)).not.toEqual(knurlXs(310, 0));
  });
});
