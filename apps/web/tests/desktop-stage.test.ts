import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
vi.mock("../components/player/playback-provider", () => ({ useNowPlaying: () => null }));
(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
import { DesktopStage } from "../components/desktop-stage";
import { qrPath } from "../lib/qr";
it("keeps the home QR stable across page changes and uses no query parameters", async () => {
  const original = window.location.href;
  const host = document.createElement("div"); document.body.append(host); const root = createRoot(host);
  try {
    window.history.replaceState({}, "", "/tune?test=one");
    await act(async () => root.render(createElement(DesktopStage)));
    const code = () => host.querySelector('.desk-qr path')?.getAttribute('d');
    expect(code()).toBe(qrPath(`${window.location.origin}/`).d);
    const initial = code();
    window.history.replaceState({}, "", "/");
    await act(async () => root.render(createElement(DesktopStage)));
    expect(code()).toBe(initial);
  } finally { await act(async () => root.unmount()); host.remove(); window.history.replaceState({}, "", original); }
});
