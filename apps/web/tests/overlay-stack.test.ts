import { describe, expect, it, vi } from "vitest";

import { closeTopOverlay, openOverlayCount, registerOverlay } from "../lib/overlay-stack";

function escape() {
  const event = new KeyboardEvent("keydown", { key: "Escape", cancelable: true });
  window.dispatchEvent(event);
  return event;
}

describe("overlay stack", () => {
  it("Esc closes only the top-most overlay", () => {
    const player = vi.fn();
    const sheet = vi.fn();
    const releasePlayer = registerOverlay(player);
    const releaseSheet = registerOverlay(sheet);
    expect(escape().defaultPrevented).toBe(true);
    expect(sheet).toHaveBeenCalledTimes(1);
    expect(player).not.toHaveBeenCalled();
    releaseSheet();
    escape();
    expect(player).toHaveBeenCalledTimes(1);
    releasePlayer();
    expect(openOverlayCount()).toBe(0);
  });

  it("does nothing with no overlay open", () => {
    expect(closeTopOverlay()).toBe(false);
    expect(escape().defaultPrevented).toBe(false);
  });

  it("releasing a lower overlay keeps the top one on top", () => {
    const a = vi.fn();
    const b = vi.fn();
    const releaseA = registerOverlay(a);
    const releaseB = registerOverlay(b);
    releaseA();
    closeTopOverlay();
    expect(b).toHaveBeenCalledTimes(1);
    expect(a).not.toHaveBeenCalled();
    releaseB();
  });
});
