import { describe, expect, it } from "vitest";

import {
  ANALYTICS_DISABLED_KEY,
  analyticsDisabled,
  beforeSendAnalytics,
  sanitizeAnalyticsUrl,
} from "../lib/analytics-filter";

const storageWith = (value: string | null) => ({ getItem: (key: string) => (key === ANALYTICS_DISABLED_KEY ? value : null) });

describe("sanitizeAnalyticsUrl", () => {
  it("drops the query string and the hash", () => {
    expect(sanitizeAnalyticsUrl("https://wavecast.space/tune?station=night&q=%E9%9B%A8")).toBe("https://wavecast.space/tune");
    expect(sanitizeAnalyticsUrl("https://wavecast.space/?c=abc#top")).toBe("https://wavecast.space/");
  });

  it("replaces the id in dynamic paths", () => {
    expect(sanitizeAnalyticsUrl("https://wavecast.space/program/proposal-abc123?c=x")).toBe("https://wavecast.space/program/[seedId]");
    expect(sanitizeAnalyticsUrl("https://wavecast.space/p/0123456789")).toBe("https://wavecast.space/p/[code]");
    expect(sanitizeAnalyticsUrl("https://wavecast.space/episode/seed-1")).toBe("https://wavecast.space/episode/[seedId]");
    expect(sanitizeAnalyticsUrl("https://wavecast.space/episode/materialized/0cbbb413-bbbd-4940")).toBe("https://wavecast.space/episode/materialized/[episodeId]");
  });

  it("leaves ordinary pages alone", () => {
    expect(sanitizeAnalyticsUrl("https://wavecast.space/library")).toBe("https://wavecast.space/library");
    expect(sanitizeAnalyticsUrl("https://wavecast.space/account")).toBe("https://wavecast.space/account");
  });

  it("copes with a value that is not a full URL", () => {
    expect(sanitizeAnalyticsUrl("/tune?station=night#x")).toBe("/tune");
  });
});

describe("opting out", () => {
  it("is off only when the key is exactly 'true'", () => {
    expect(analyticsDisabled(storageWith("true"))).toBe(true);
    expect(analyticsDisabled(storageWith("false"))).toBe(false);
    expect(analyticsDisabled(storageWith(null))).toBe(false);
    expect(analyticsDisabled(null)).toBe(false);
  });

  it("does not break when storage throws", () => {
    expect(analyticsDisabled({ getItem: () => { throw new Error("blocked"); } })).toBe(false);
  });

  it("drops the event for an opted-out browser and sanitises it for everyone else", () => {
    const event = { type: "pageview" as const, url: "https://wavecast.space/program/abc?c=1" };
    expect(beforeSendAnalytics(event, storageWith("true"))).toBeNull();
    expect(beforeSendAnalytics(event, storageWith(null))).toEqual({ type: "pageview", url: "https://wavecast.space/program/[seedId]" });
  });
});
