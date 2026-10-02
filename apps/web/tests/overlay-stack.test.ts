import { describe, expect, it, vi } from "vitest";

import { closeTopOverlay, detachOverlayHistory, openOverlayCount, registerOverlay } from "../lib/overlay-stack";

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

const tick = (ms = 30) => new Promise((resolve) => setTimeout(resolve, ms));

describe("overlay stack history (Android back)", () => {
  it("pushes a same-URL entry while open and Back closes only the top overlay", async () => {
    const url = window.location.href;
    const startLength = window.history.length;
    const lower = vi.fn();
    const upper = vi.fn();
    const releaseLower = registerOverlay(lower, { history: true });
    await tick();
    const releaseUpper = registerOverlay(upper, { history: true });
    await tick();
    expect(window.history.length).toBe(startLength + 2);
    expect(window.location.href).toBe(url);

    window.history.back();
    await tick();
    expect(upper).toHaveBeenCalledTimes(1);
    expect(lower).not.toHaveBeenCalled();
    releaseUpper(); // the overlay unmounts after closing: no extra back
    await tick();
    expect((window.history.state as { wcOverlay?: number }).wcOverlay).toBe(1);

    window.history.back();
    await tick();
    expect(lower).toHaveBeenCalledTimes(1);
    releaseLower();
    await tick();
    expect(window.history.state?.wcOverlay).toBeUndefined();
  });

  it("closing by other means removes its entry without closing anything else", async () => {
    const base = window.history.state?.wcOverlay ?? 0;
    const other = vi.fn();
    const sheet = vi.fn();
    const releaseOther = registerOverlay(other, { history: true });
    await tick();
    const releaseSheet = registerOverlay(sheet, { history: true });
    await tick();
    expect(window.history.state.wcOverlay).toBe(base + 2);
    releaseSheet(); // e.g. the 取消 button
    await tick();
    expect(window.history.state.wcOverlay).toBe(base + 1);
    expect(other).not.toHaveBeenCalled();
    expect(sheet).not.toHaveBeenCalled();
    releaseOther();
    await tick();
  });

  it("an overlay mounted and unmounted at once never touches history", async () => {
    const before = window.history.length;
    const release = registerOverlay(vi.fn(), { history: true });
    release();
    await tick();
    expect(window.history.length).toBe(before);
  });

  it("detached overlays are not closed by later pops", async () => {
    const tuning = vi.fn();
    const release = registerOverlay(tuning, { history: true });
    await tick();
    detachOverlayHistory();
    window.history.replaceState(null, "", window.location.href);
    window.history.back();
    await tick();
    expect(tuning).not.toHaveBeenCalled();
    release();
  });
});
