import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
import { PullToRefresh } from "../components/home/pull-to-refresh";
import { PULL_MIN_REFRESH_MS } from "../lib/pull-refresh";

let root: Root;
let scroller: HTMLDivElement;
const onRefresh = vi.fn(() => Promise.resolve());
const onBlocked = vi.fn();

beforeEach(() => {
  vi.useFakeTimers();
  // Reduced motion: the springs jump straight to their target.
  vi.stubGlobal("matchMedia", () => ({ matches: true }));
  onRefresh.mockClear();
  onBlocked.mockClear();
  scroller = document.createElement("div");
  scroller.className = "app-scroll";
  document.body.append(scroller);
  root = createRoot(scroller);
});
afterEach(async () => {
  await act(async () => root.unmount());
  scroller.remove();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

async function mount(canRefresh: boolean) {
  await act(async () => root.render(createElement(PullToRefresh, { canRefresh, onRefresh, onBlocked, children: createElement("p", null, "页面") })));
}
function touch(type: string, y: number, x = 100) {
  const event = Object.assign(new Event(type, { bubbles: true, cancelable: true }), { touches: [{ clientX: x, clientY: y }] });
  scroller.dispatchEvent(event);
  return event;
}
const content = () => scroller.querySelector<HTMLElement>(".pull-content")!;
const logo = () => scroller.querySelector<HTMLElement>(".pull-logo")!;

it("follows a downward drag, shows the logo, and refreshes on a long pull", async () => {
  await mount(true);
  expect(logo().style.opacity).toBe("0");
  await act(async () => { touch("touchstart", 100); });
  let move!: Event;
  await act(async () => { move = touch("touchmove", 300); });
  expect(move.defaultPrevented).toBe(true);
  expect(content().style.transform).toMatch(/translateY\(\d/);
  expect(logo().style.opacity).toBe("1");
  await act(async () => { touch("touchend", 300); });
  expect(onRefresh).toHaveBeenCalledTimes(1);
  expect(scroller.querySelector("[data-swing]")).not.toBeNull();
  await act(async () => { await vi.advanceTimersByTimeAsync(PULL_MIN_REFRESH_MS); });
  expect(scroller.querySelector("[data-swing]")).toBeNull();
  expect(content().style.transform).toBe("");
});

it("springs back without refreshing when the pull is short", async () => {
  await mount(true);
  await act(async () => { touch("touchstart", 100); });
  await act(async () => { touch("touchmove", 150); });
  await act(async () => { touch("touchend", 150); });
  expect(onRefresh).not.toHaveBeenCalled();
  expect(onBlocked).not.toHaveBeenCalled();
  expect(content().style.transform).toBe("");
});

it("asks a guest to sign in instead of refreshing", async () => {
  await mount(false);
  await act(async () => { touch("touchstart", 100); });
  await act(async () => { touch("touchmove", 300); });
  await act(async () => { touch("touchend", 300); });
  expect(onRefresh).not.toHaveBeenCalled();
  expect(onBlocked).toHaveBeenCalledTimes(1);
  expect(content().style.transform).toBe("");
});

it("leaves the gesture to the browser when the page is scrolled, or the drag is upward or sideways", async () => {
  await mount(true);
  scroller.scrollTop = 40;
  await act(async () => { touch("touchstart", 100); });
  let move!: Event;
  await act(async () => { move = touch("touchmove", 300); });
  expect(move.defaultPrevented).toBe(false);

  scroller.scrollTop = 0;
  await act(async () => { touch("touchstart", 300); });
  await act(async () => { move = touch("touchmove", 200); });
  expect(move.defaultPrevented).toBe(false);

  await act(async () => { touch("touchstart", 100, 100); });
  await act(async () => { move = touch("touchmove", 130, 260); });
  expect(move.defaultPrevented).toBe(false);
  expect(content().style.transform).toBe("");
});
