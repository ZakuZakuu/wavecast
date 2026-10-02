import { describe, expect, it } from "vitest";

import { dedupeByProgramme, isFinished, listeningStatus, progressRatio, relativeWhen } from "../lib/library-view";

const now = new Date(2026, 9, 2, 15, 0, 0).getTime(); // Friday
const record = (seedId: string, episodeId: string, updatedAt: number, progressSeconds = 0, durationSeconds = 1800) => ({
  seedId, episodeId, updatedAt, progressSeconds, durationSeconds, title: "t", topic: null, currentTitle: "Track Intro",
});

describe("library dedupe", () => {
  it("keeps only the most recent record per programme", () => {
    const rows = dedupeByProgramme([
      record("a", "a1", now - 5000),
      record("b", "b1", now - 1000),
      record("a", "a2", now - 100),
      record("a", "a0", now - 99999),
    ]);
    expect(rows.map((row) => row.episodeId)).toEqual(["a2", "b1"]);
  });
});

describe("listening status", () => {
  it("formats relative days", () => {
    expect(relativeWhen(now - 60_000, now)).toBe("刚刚");
    expect(relativeWhen(now - 20 * 60_000, now)).toBe("20 分钟前");
    expect(relativeWhen(now - 3 * 3600_000, now)).toBe("今天");
    expect(relativeWhen(now - 24 * 3600_000, now)).toBe("昨天");
    expect(relativeWhen(new Date(2026, 8, 29, 10).getTime(), now)).toBe("周二");
    expect(relativeWhen(new Date(2026, 8, 12, 10).getTime(), now)).toBe("9月12日");
  });

  it("reports progress or completion without internal segment names", () => {
    expect(listeningStatus(record("a", "a", now - 1000, 760), now)).toBe("听到 12:40，刚刚");
    expect(listeningStatus(record("a", "a", now - 24 * 3600_000, 1798), now)).toBe("听完了，昨天");
    expect(listeningStatus(record("a", "a", now, 760), now)).not.toContain("Track Intro");
    expect(isFinished(1795, 1800)).toBe(true);
    expect(progressRatio(900, 1800)).toBe(0.5);
    expect(progressRatio(10, 0)).toBe(0);
  });
});

import { swipeDecision } from "../components/library/swipe-row";

describe("swipe decision", () => {
  it("opens past 40px, deletes past 60% of the row, honours flings", () => {
    expect(swipeDecision(-30, 350, 0)).toBe("close");
    expect(swipeDecision(-41, 350, 0)).toBe("open");
    expect(swipeDecision(-211, 350, 0)).toBe("delete");
    expect(swipeDecision(-20, 350, -0.8)).toBe("open");
    expect(swipeDecision(-80, 350, 0.8)).toBe("close");
  });
});
