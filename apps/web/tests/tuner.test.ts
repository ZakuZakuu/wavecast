import { describe, expect, it } from "vitest";

import { STATIONS } from "../lib/stations";
import { cardNoise, clampFreq, DIAL_HEIGHT, freqAfterDrag, freqToX, fullScaleGeometry, nearestStation, neighbourStation, noiseForDistance, posterPose, PX_PER_MHZ, readTuner, scaleTranslate, scaleX, snapTarget, STATION_FADE_MHZ, stationBlends, stepStation, tickGeometry, tintBlend, wheelDeltaPx } from "../lib/tuner";

describe("scale conversion", () => {
  it("maps 28px to 1 MHz around the centred pointer", () => {
    expect(PX_PER_MHZ).toBe(28);
    expect(freqToX(97.4, 97.4, 310)).toBe(155);
    expect(freqToX(98.4, 97.4, 310)).toBeCloseTo(183);
    expect(freqAfterDrag(97.4, 28)).toBeCloseTo(96.4);
    expect(freqAfterDrag(97.4, -56)).toBeCloseTo(99.4);
  });

  it("puts about 120px between two stations, with a whole neighbour on each side of a 322px window", () => {
    expect(Math.round((97.4 - 93.1) * PX_PER_MHZ)).toBe(120);
    // A neighbour's name (about 66px with its dot) must lie inside the window's half width of 161px.
    const widest = Math.max(...[88.7, 93.1, 97.4, 101.5, 105.8].slice(1).map((f, i) => (f - [88.7, 93.1, 97.4, 101.5, 105.8][i]) * PX_PER_MHZ));
    expect(widest + 33).toBeLessThan(161);
  });

  it("clamps to 87.5–108", () => {
    expect(clampFreq(80)).toBe(87.5);
    expect(clampFreq(120)).toBe(108);
    expect(freqAfterDrag(88, 1000)).toBe(87.5);
  });

  it("draws a 0.2 MHz scale with integer / half / minor heights", () => {
    const ticks = tickGeometry(97.4, 310);
    expect(ticks.major).toContain("V56");
    // On a 0.2 MHz grid x.5 never occurs, so minor ticks are all 6px.
    const heights = new Set([...ticks.minor.matchAll(/M[\d.]+ ([\d.]+)V56/g)].map((m) => 56 - Number(m[1])));
    expect([...heights]).toEqual([6]);
    expect(new Set([...ticks.major.matchAll(/M[\d.]+ ([\d.]+)V56/g)].map((m) => 56 - Number(m[1])))).toEqual(new Set([16]));
    expect(DIAL_HEIGHT).toBe(64);
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
    expect(readTuner(97.5)).toMatchObject({ locked: true, between: false });
    expect(readTuner(97.65)).toMatchObject({ locked: false, between: false });
    expect(readTuner(95.2)).toMatchObject({ locked: false, between: true });
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

describe("full scale layer", () => {
  it("draws 87.5–108 once and positions it with translateX only", () => {
    const full = fullScaleGeometry();
    expect(scaleX(87.5)).toBe(0);
    expect(scaleX(88)).toBeCloseTo(14);
    expect(scaleTranslate(97.4, 310)).toBeCloseTo(155 - (97.4 - 87.5) * PX_PER_MHZ);
    const first = full.major.match(/M([\d.]+) /);
    expect(Number(first![1])).toBeCloseTo(scaleX(88), 1);
  });

  it("raises noise continuously with distance", () => {
    expect(noiseForDistance(0)).toBe(0);
    expect(noiseForDistance(0.15)).toBe(0);
    const samples = [0.2, 0.3, 0.5, 0.8, 1.1].map(noiseForDistance);
    for (let i = 1; i < samples.length; i += 1) expect(samples[i]).toBeGreaterThan(samples[i - 1]);
    expect(noiseForDistance(2)).toBe(1);
    expect(Math.abs(noiseForDistance(0.301) - noiseForDistance(0.299))).toBeLessThan(0.01);
  });
});

describe("wheelDeltaPx", () => {
  it("uses the dominant axis so both horizontal and vertical scrolling tune", () => {
    expect(wheelDeltaPx({ deltaX: 30, deltaY: 4, deltaMode: 0 })).toBe(30);
    expect(wheelDeltaPx({ deltaX: -2, deltaY: -40, deltaMode: 0 })).toBe(-40);
  });

  it("normalises line and page delta modes", () => {
    expect(wheelDeltaPx({ deltaX: 0, deltaY: 3, deltaMode: 1 })).toBe(48);
    expect(wheelDeltaPx({ deltaX: 0, deltaY: 1, deltaMode: 2 }, 300)).toBe(300);
  });
});

describe("the card between stations", () => {
  it("shows a station fully on it and not at all half-way to the next", () => {
    const [casual, crate] = stationBlends(88.7);
    expect(casual).toMatchObject({ weight: 1, away: 0, distance: 0 });
    expect(crate.weight).toBe(0);
    const half = stationBlends(88.7 + STATION_FADE_MHZ);
    expect(half[0].weight).toBeCloseTo(0);
    expect(half[0].away).toBe(1);
  });

  it("depends on the distance only, so the same from either side", () => {
    const left = stationBlends(97.4 - 1.2).find((item) => item.station.id === "portrait");
    const right = stationBlends(97.4 + 1.2).find((item) => item.station.id === "portrait");
    expect(left?.weight).toBeCloseTo(right?.weight ?? -1);
    expect(left?.weight).toBeCloseTo(1 - 1.2 / STATION_FADE_MHZ);
  });

  it("lays the next station's tint over the nearest, equally from both sides of the half-way point", () => {
    expect(tintBlend(93.1)).toMatchObject({ amount: 0 });
    const before = tintBlend(95.2);
    const after = tintBlend(95.3);
    expect(before.base.id).toBe("crate");
    expect(after.base.id).toBe("portrait");
    // Nearly the same mix of the two, so the colour does not jump as the nearest station changes.
    expect(Math.abs(before.amount - (1 - after.amount))).toBeLessThan(0.03);
    expect(before.amount).toBeLessThan(0.5);
  });

  it("flies the picture off to the right and up, growing and turning", () => {
    expect(posterPose(0)).toEqual({ x: 0, y: -0, rotate: 6, scale: 1 });
    const away = posterPose(1);
    expect(away.x).toBeGreaterThan(250);
    expect(away.y).toBeLessThan(0);
    expect(away.rotate).toBeGreaterThan(6);
    expect(away.scale).toBeGreaterThan(1);
    // Slow near the station, fast away from it.
    expect(posterPose(0.25).x).toBeLessThan(posterPose(0.5).x / 3);
  });

  it("puts static over the card only between two stations", () => {
    expect(cardNoise(0)).toBe(0);
    expect(cardNoise(0.9)).toBe(0);
    expect(cardNoise(STATION_FADE_MHZ)).toBeCloseTo(0.7);
    expect(cardNoise(1.5)).toBeGreaterThan(cardNoise(1.1));
  });
});

describe("stepping along the band", () => {
  it("finds the next station up or down from any frequency, and none past the ends", () => {
    expect(neighbourStation(93.1, 1)?.name).toBe("人物志");
    expect(neighbourStation(93.1, -1)?.name).toBe("随便听");
    expect(neighbourStation(95.2, -1)?.name).toBe("唱片行");
    expect(neighbourStation(95.2, 1)?.name).toBe("人物志");
    expect(neighbourStation(88.7, -1)).toBeNull();
    expect(neighbourStation(105.8, 1)).toBeNull();
    expect(neighbourStation(87.5, 1)?.name).toBe("随便听");
  });
});
