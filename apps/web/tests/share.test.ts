import { beforeEach, describe, expect, it } from "vitest";

import { rememberCoverSource } from "../lib/cover/programme-cover";
import {
  adoptedCopies,
  displayShareUrl,
  forgetAdoptedCopy,
  GUEST_IDENTITY,
  programmeShareUrl,
  rememberAdoptedCopy,
  shortCodeFor,
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

  it("keeps a visitor's copy per identity: another account does not inherit it", () => {
    rememberAdoptedCopy("proposal-orig", "proposal-copy-a", "user-a");
    expect(adoptedCopies("proposal-orig", "user-a")).toEqual(["proposal-copy-a"]);
    expect(adoptedCopies("proposal-orig", "user-b")).toEqual([]);
    expect(adoptedCopies("proposal-orig", GUEST_IDENTITY)).toEqual([]);
  });

  it("offers a guest's copy to the account the guest signs in to, to be checked with the server", () => {
    rememberAdoptedCopy("proposal-orig", "proposal-guest-copy", GUEST_IDENTITY);
    expect(adoptedCopies("proposal-orig", "user-a")).toEqual(["proposal-guest-copy"]);
    rememberAdoptedCopy("proposal-orig", "proposal-own-copy", "user-a");
    expect(adoptedCopies("proposal-orig", "user-a")).toEqual(["proposal-own-copy", "proposal-guest-copy"]);
  });

  it("forgets a copy the server does not know, wherever it was recorded", () => {
    rememberAdoptedCopy("proposal-orig", "proposal-copy", GUEST_IDENTITY);
    rememberAdoptedCopy("proposal-orig", "proposal-copy", "user-a");
    forgetAdoptedCopy("proposal-orig", "proposal-copy");
    expect(adoptedCopies("proposal-orig", "user-a")).toEqual([]);
    expect(adoptedCopies("proposal-orig", GUEST_IDENTITY)).toEqual([]);
  });
});
