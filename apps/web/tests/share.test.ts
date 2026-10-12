import { beforeEach, describe, expect, it } from "vitest";

import { rememberCoverSource } from "../lib/cover/programme-cover";
import { displayShareUrl, programmeShareUrl } from "../lib/share";

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

  it("points at the programme page on the given origin", () => {
    expect(programmeShareUrl("proposal-abc", "https://wavecast.space")).toBe("https://wavecast.space/program/proposal-abc");
  });

  it("carries the cover a card was made from, so the recipient sees the same cover", () => {
    rememberCoverSource("proposal-abc", "idea-7");
    expect(programmeShareUrl("proposal-abc", "https://wavecast.space")).toBe(
      "https://wavecast.space/program/proposal-abc?c=idea-7",
    );
  });

  it("shows the address without its scheme", () => {
    expect(displayShareUrl("https://wavecast.space/program/k3f9x2")).toBe("wavecast.space/program/k3f9x2");
  });
});
