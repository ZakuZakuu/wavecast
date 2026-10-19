import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/api", () => ({
  api: { programmePublication: vi.fn() },
  ApiRequestError: class extends Error { constructor(message: string, readonly status: number) { super(message); } },
}));

import { api, ApiRequestError } from "../lib/api";
import {
  isBeingMade,
  pollWatchedPublications,
  readWatchedPublications,
  unwatchPublication,
  watchPublication,
} from "../lib/publications";
import type { PublicationItem } from "../lib/types";

const item = (over: Partial<PublicationItem> = {}): PublicationItem => ({
  id: "pub-" + "a".repeat(32), code: "a".repeat(10), episode_id: "ep", status: "mixing", visibility: "link", step: "mix", progress: 50, ...over,
});

beforeEach(() => {
  window.localStorage.clear();
  vi.mocked(api.programmePublication).mockReset();
});

describe("the publications this device is waiting for", () => {
  it("remembers a programme once, and forgets it when asked", () => {
    watchPublication({ programmeId: "p1", title: "一档" });
    watchPublication({ programmeId: "p1", title: "一档" });
    watchPublication({ programmeId: "p2", title: "另一档" });
    expect(readWatchedPublications().map((watch) => watch.programmeId)).toEqual(["p1", "p2"]);
    unwatchPublication("p1");
    expect(readWatchedPublications().map((watch) => watch.programmeId)).toEqual(["p2"]);
  });

  it("drops what has been waited for too long", () => {
    watchPublication({ programmeId: "old", title: "旧" });
    expect(readWatchedPublications(Date.now() + 60 * 60 * 1000)).toEqual([]);
  });

  it("reports the ones that can be shared now, keeps asking about the ones still being made, and lets the rest go", async () => {
    watchPublication({ programmeId: "done", title: "好了" });
    watchPublication({ programmeId: "busy", title: "还在做" });
    watchPublication({ programmeId: "failed", title: "失败" });
    watchPublication({ programmeId: "gone", title: "没了" });
    watchPublication({ programmeId: "flaky", title: "网络问题" });
    vi.mocked(api.programmePublication).mockImplementation(async (id: string) => {
      if (id === "done") return item({ status: "published", step: "done", progress: 100 });
      if (id === "busy") return item();
      if (id === "failed") return item({ status: "failed", step: "done", progress: 0 });
      if (id === "gone") throw new ApiRequestError("none", 404);
      throw new ApiRequestError("boom", 500);
    });

    const finished = await pollWatchedPublications();

    expect(finished.map((watch) => watch.programmeId)).toEqual(["done"]);
    // A failure to ask is not an answer: that one is asked about again.
    expect(readWatchedPublications().map((watch) => watch.programmeId)).toEqual(["busy", "flaky"]);
  });

  it("asks about nothing when nothing is waited for", async () => {
    expect(await pollWatchedPublications()).toEqual([]);
    expect(api.programmePublication).not.toHaveBeenCalled();
  });

  it("knows what is still being made", () => {
    expect(isBeingMade(item({ status: "preparing" }))).toBe(true);
    expect(isBeingMade(item({ status: "mixing" }))).toBe(true);
    expect(isBeingMade(item({ status: "published" }))).toBe(false);
    expect(isBeingMade(null)).toBe(false);
    expect(isBeingMade(undefined)).toBe(false);
  });
});
