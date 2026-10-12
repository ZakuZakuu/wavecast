import { describe, expect, it } from "vitest";

import { prefersNativeHls } from "../lib/program-stream";

const nativeHls = (type: string) => (type.includes("mpegurl") || type.includes("mpegURL") ? "maybe" : "");
const noHls = () => "";

const UA = {
  chrome: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
  edge: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36 Edg/142.0.0.0",
  androidChrome: "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Mobile Safari/537.36",
  headlessChrome: "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/155.0.0.0 Safari/537.36",
  safariMac: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
  safariIphone: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
  chromeIos: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/126.0.0.0 Mobile/15E148 Safari/604.1",
  edgeIos: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 EdgiOS/126.0 Mobile/15E148 Safari/605.1.15",
};

describe("prefersNativeHls", () => {
  it("sends Chromium browsers to hls.js even though they now answer 'maybe' for HLS", () => {
    for (const ua of [UA.chrome, UA.edge, UA.androidChrome, UA.headlessChrome]) {
      expect(prefersNativeHls(nativeHls, ua)).toBe(false);
    }
  });

  it("keeps Safari and every iOS browser (WebKit) on the native player", () => {
    for (const ua of [UA.safariMac, UA.safariIphone, UA.chromeIos, UA.edgeIos]) {
      expect(prefersNativeHls(nativeHls, ua)).toBe(true);
    }
  });

  it("never uses native playback where the browser cannot play HLS", () => {
    expect(prefersNativeHls(noHls, UA.safariMac)).toBe(false);
    expect(prefersNativeHls(noHls, UA.chrome)).toBe(false);
  });
});
