import { describe, expect, it } from "vitest";

import { detectPlatform, shouldOfferInstall, type InstallContext } from "../lib/install";

const base: InstallContext = {
  platform: "ios-safari", standalone: false, visits: 1, finishedProgramme: false,
  snoozedUntil: 0, acknowledged: false, now: 1_000_000,
};

describe("install guide conditions", () => {
  it("never shows on first open, only after a finished programme or a second visit", () => {
    expect(shouldOfferInstall(base)).toBe(false);
    expect(shouldOfferInstall({ ...base, visits: 2 })).toBe(true);
    expect(shouldOfferInstall({ ...base, finishedProgramme: true })).toBe(true);
  });

  it("is hidden when already installed, acknowledged or snoozed", () => {
    expect(shouldOfferInstall({ ...base, visits: 3, standalone: true })).toBe(false);
    expect(shouldOfferInstall({ ...base, visits: 3, acknowledged: true })).toBe(false);
    expect(shouldOfferInstall({ ...base, visits: 3, snoozedUntil: base.now + 1 })).toBe(false);
    expect(shouldOfferInstall({ ...base, visits: 3, snoozedUntil: base.now - 1 })).toBe(true);
    expect(shouldOfferInstall({ ...base, visits: 3, platform: "other" })).toBe(false);
  });

  it("is never offered on a computer (the desktop side card has a QR code)", () => {
    expect(shouldOfferInstall({ ...base, visits: 3, desktop: true })).toBe(false);
    expect(shouldOfferInstall({ ...base, visits: 3, platform: "installable", desktop: true })).toBe(false);
    expect(shouldOfferInstall({ ...base, visits: 3, platform: "installable" })).toBe(true);
  });

  it("detects iOS Safari vs other browsers", () => {
    const iphoneSafari = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1";
    const iphoneChrome = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/129.0 Mobile/15E148 Safari/604.1";
    const ipadOS = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15";
    const android = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Mobile Safari/537.36";
    expect(detectPlatform(iphoneSafari, 5, false)).toBe("ios-safari");
    expect(detectPlatform(iphoneChrome, 5, false)).toBe("other");
    expect(detectPlatform(ipadOS, 5, false)).toBe("ios-safari");
    expect(detectPlatform(ipadOS, 0, false)).toBe("other");
    expect(detectPlatform(android, 5, true)).toBe("installable");
    expect(detectPlatform(android, 5, false)).toBe("other");
  });
});
