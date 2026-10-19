import { beforeEach, describe, expect, it } from "vitest";

import { rememberCoverSource } from "../lib/cover/programme-cover";
import {
  displayShareUrl,
  isGeneratedProgramme,
  programmeShareUrl,
  publicationCode,
  publishedShareUrl,
} from "../lib/share";

function installStorage() {
  const data = new Map<string, string>();
  const storage = {
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => void data.set(key, value),
    removeItem: (key: string) => void data.delete(key),
  };
  Object.defineProperty(globalThis, "window", { value: { localStorage: storage }, configurable: true });
}

const PUBLISHED = "pub-3fa9c2b1d4e84f0a9b7c5d6e7f801234";

describe("programme share links", () => {
  beforeEach(installStorage);

  it("points a built-in programme at its page on the given origin", () => {
    expect(programmeShareUrl("city-pop-misunderstood", "https://wavecast.space")).toBe(
      "https://wavecast.space/program/city-pop-misunderstood",
    );
  });

  it("gives a published programme a short link made of the first ten digits of its id", () => {
    expect(publicationCode(PUBLISHED)).toBe("3fa9c2b1d4");
    expect(publicationCode("proposal-3fa9c2b1d4e84f0a9b7c5d6e7f801234")).toBeNull();
    expect(publicationCode("pub-abc")).toBeNull();
  });

  it("carries the cover of the card a programme was made from, so the recipient sees the same cover", () => {
    rememberCoverSource("proposal-own", "idea-7");
    expect(publishedShareUrl(PUBLISHED, "proposal-own", "https://wavecast.space")).toBe(
      "https://wavecast.space/p/3fa9c2b1d4?c=idea-7",
    );
    // Without a card of its own the cover follows the source programme's id.
    expect(publishedShareUrl(PUBLISHED, "proposal-plain", "https://wavecast.space")).toBe(
      "https://wavecast.space/p/3fa9c2b1d4?c=proposal-plain",
    );
  });

  it("knows which programmes are shared by publishing them", () => {
    expect(isGeneratedProgramme("proposal-3fa9c2b1d4e84f0a9b7c5d6e7f801234")).toBe(true);
    expect(isGeneratedProgramme(PUBLISHED)).toBe(false);
    expect(isGeneratedProgramme("city-pop-misunderstood")).toBe(false);
  });

  it("shows the address without its scheme", () => {
    expect(displayShareUrl("https://wavecast.space/p/3fa9c2b1d4")).toBe("wavecast.space/p/3fa9c2b1d4");
  });
});
