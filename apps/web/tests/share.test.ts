import { beforeEach, describe, expect, it } from "vitest";

import { rememberCoverSource } from "../lib/cover/programme-cover";
import { displayShareUrl, programmeShareUrl, shortCodeFor } from "../lib/share";

function installStorage() {
  const data = new Map<string, string>();
  const storage = {
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => void data.set(key, value),
    removeItem: (key: string) => void data.delete(key),
  };
  Object.defineProperty(globalThis, "window", { value: { localStorage: storage }, configurable: true });
}

describe("programme share links", () => {
  beforeEach(installStorage);

  it("points a built-in programme at its page on the given origin", () => {
    expect(programmeShareUrl("city-pop-misunderstood", "https://wavecast.space")).toBe(
      "https://wavecast.space/program/city-pop-misunderstood",
    );
  });

  it("gives a generated programme a short link made of the first ten digits of its id", () => {
    const id = "proposal-3fa9c2b1d4e84f0a9b7c5d6e7f801234";
    expect(shortCodeFor(id)).toBe("3fa9c2b1d4");
    expect(programmeShareUrl(id, "https://wavecast.space")).toBe("https://wavecast.space/p/3fa9c2b1d4");
    expect(shortCodeFor("proposal-abc")).toBeNull();
    expect(shortCodeFor("featured-casual-commute")).toBeNull();
  });

  it("carries the cover a card was made from, so the recipient sees the same cover", () => {
    const id = "proposal-3fa9c2b1d4e84f0a9b7c5d6e7f801234";
    rememberCoverSource(id, "idea-7");
    expect(programmeShareUrl(id, "https://wavecast.space")).toBe("https://wavecast.space/p/3fa9c2b1d4?c=idea-7");
  });

  it("shows the address without its scheme", () => {
    expect(displayShareUrl("https://wavecast.space/program/k3f9x2")).toBe("wavecast.space/program/k3f9x2");
  });
});
