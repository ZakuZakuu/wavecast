import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

import { useTuner, type Tuner } from "../components/tune/use-tuner";
import { stationById } from "../lib/stations";

let root: Root;
let host: HTMLDivElement;
let tuner: Tuner;

function Probe() {
  tuner = useTuner();
  return null;
}

beforeEach(() => {
  window.localStorage.clear();
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "requestAnimationFrame", "cancelAnimationFrame", "performance", "Date"] });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.useRealTimers();
});

const mount = () => act(async () => root.render(createElement(Probe)));
const run = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });

/** A pointer event as far as the tuner reads it. */
function pointer(x: number, y = 0) {
  return {
    button: 0,
    pointerType: "touch",
    pointerId: 1,
    clientX: x,
    clientY: y,
    target: document.body,
    currentTarget: { setPointerCapture: vi.fn() },
  } as unknown as React.PointerEvent<HTMLElement>;
}

describe("the tuner", () => {
  it("starts a first-time listener on 唱片行", async () => {
    await mount();
    expect(tuner.station.id).toBe("crate");
    expect(tuner.freq).toBe(stationById("crate").freq);
  });

  it("steps to the neighbouring station, and not past either end of the band", async () => {
    await mount();
    expect(tuner.canStep).toEqual({ down: true, up: true });
    await act(async () => tuner.step(1));
    await run(700);
    expect(tuner.station.id).toBe("portrait");
    await act(async () => tuner.step(-1));
    await act(async () => tuner.step(-1));
    await run(700);
    expect(tuner.station.id).toBe("casual");
    expect(tuner.canStep.down).toBe(false);
    await act(async () => tuner.step(-1));
    await run(700);
    expect(tuner.station.id).toBe("casual");
  });

  it("goes on from where a slide is heading: two quick taps are two stations", async () => {
    await mount();
    await act(async () => tuner.step(1));
    await run(120);
    await act(async () => tuner.step(1));
    await run(900);
    expect(tuner.station.id).toBe("lineage");
    expect(tuner.freq).toBeCloseTo(stationById("lineage").freq, 1);
  });

  it("is not stopped by a tap on the card while it slides (it used to stay between two stations)", async () => {
    await mount();
    await act(async () => tuner.step(1));
    await run(150);
    expect(tuner.freq).toBeGreaterThan(stationById("crate").freq);
    expect(tuner.freq).toBeLessThan(stationById("portrait").freq);
    // A tap on the card: press and lift in the same place.
    await act(async () => tuner.swipe.onPointerDown(pointer(200, 100)));
    await act(async () => tuner.swipe.onPointerUp(pointer(200, 100)));
    await run(900);
    expect(tuner.freq).toBeCloseTo(stationById("portrait").freq, 1);
  });

  it("settles on a station after a tap on the dial in mid-slide", async () => {
    await mount();
    await act(async () => tuner.step(1));
    await run(150);
    await act(async () => tuner.dial.onPointerDown(pointer(150, 30)));
    await act(async () => tuner.dial.onPointerUp(pointer(150, 30)));
    await run(900);
    const nearest = tuner.reading.station;
    expect(tuner.freq).toBeCloseTo(nearest.freq, 1);
  });

  it("never rests between two stations, whatever stopped it", async () => {
    await mount();
    // A swipe that takes the dial half-way and is then lost (no pointer-up ever arrives).
    await act(async () => tuner.swipe.onPointerDown(pointer(300, 100)));
    await act(async () => tuner.swipe.onPointerMove(pointer(260, 100)));
    await act(async () => tuner.swipe.onPointerMove(pointer(230, 100)));
    expect(tuner.dragging).toBe(true);
    await act(async () => tuner.swipe.onPointerCancel(pointer(230, 100)));
    await run(1200);
    expect(tuner.freq).toBeCloseTo(tuner.reading.station.freq, 1);
  });

  it("does not stay in a drag when the mouse button was released outside the dial", async () => {
    await mount();
    const mouse = (x: number, buttons: number) => ({ ...pointer(x), pointerType: "mouse", buttons }) as unknown as React.PointerEvent<HTMLElement>;
    await act(async () => tuner.dial.onPointerDown(mouse(200, 1)));
    await act(async () => tuner.dial.onPointerMove(mouse(150, 1)));
    expect(tuner.dragging).toBe(true);
    // The button came up elsewhere, so no pointer-up ever arrived; the next move says nothing is pressed.
    await act(async () => tuner.dial.onPointerMove(mouse(120, 0)));
    expect(tuner.dragging).toBe(false);
    await run(1200);
    expect(tuner.freq).toBeCloseTo(tuner.reading.station.freq, 1);
  });
});
