import { describe, expect, it } from "vitest";

import { avatarInitial, libraryProgrammeCount, providerLabel, signInProviders, tasteSummary } from "../lib/account";
import { emptyUserLibrary } from "../lib/user-library";

describe("account helpers", () => {
  it("shows only configured providers, GitHub first, none when sign-in is off", () => {
    expect(signInProviders({ enabled: true, providers: ["google", "github"] })).toEqual(["github", "google"]);
    expect(signInProviders({ enabled: true, providers: ["google"] })).toEqual(["google"]);
    expect(signInProviders({ enabled: false, providers: ["github"] })).toEqual([]);
    expect(signInProviders(null)).toEqual([]);
  });

  it("labels the sign-in provider", () => {
    expect(providerLabel("github")).toBe("通过 GitHub 登录");
    expect(providerLabel("google")).toBe("通过 Google 登录");
    expect(providerLabel("credential")).toBeNull();
  });

  it("summarises taste", () => {
    expect(tasteSummary(null)).toBeNull();
    expect(tasteSummary({ genres: ["R&B", "爵士"], artists: "City Pop", moments: [], updatedAt: 0 })).toBe("R&B、爵士、City Pop");
    expect(tasteSummary({ genres: [], artists: " ", moments: ["通勤"], updatedAt: 0 })).toBeNull();
  });

  it("counts distinct programmes in the library", () => {
    const library = emptyUserLibrary();
    const record = { episodeId: "e1", seedId: "s1", title: "t", topic: null, currentTitle: null, updatedAt: 1, progressSeconds: 0, durationSeconds: 0 };
    library.recentPrograms.push(record, { ...record, episodeId: "e2" });
    library.savedEpisodes.push({ ...record, seedId: "s2", savedAt: 1 });
    library.createdProgramIds.push("s1", "s3");
    expect(libraryProgrammeCount(library)).toBe(3);
  });

  it("picks an avatar initial", () => {
    expect(avatarInitial("rain", null)).toBe("R");
    expect(avatarInitial(" ", "zz@x.io")).toBe("Z");
    expect(avatarInitial(null, null)).toBe("W");
  });
});
