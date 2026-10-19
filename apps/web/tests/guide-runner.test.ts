import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("../lib/auth-client", () => ({ authClient: { useSession: () => ({ data: null, isPending: false }) } }));

import { GuideRunner } from "../components/guide/guide";
import type { GuideTrigger } from "../lib/guide/registry";
import { readSeenGuides } from "../lib/guide/state";
import { registerOverlay } from "../lib/overlay-stack";

let root: Root;
let host: HTMLDivElement;
const onNavigate = vi.fn();

const MARKERS = ["home-feature", "home-stations", "nav-tune", "home-picks-head", "tune-dial", "tune-input", "tune-choices", "tune-onair", "tune-prepare"];

beforeEach(() => {
  vi.useFakeTimers();
  window.localStorage.clear();
  window.sessionStorage.clear();
  onNavigate.mockClear();
  Element.prototype.scrollIntoView = vi.fn();
  for (const name of MARKERS) {
    const element = document.createElement("div");
    element.dataset.guide = name;
    document.body.append(element);
  }
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  document.body.innerHTML = "";
  vi.useRealTimers();
});

async function mount(props: { trigger?: GuideTrigger; signedIn?: boolean | null; ready?: boolean } = {}) {
  await act(async () => {
    root.render(createElement(GuideRunner, { trigger: "home", signedIn: false, ready: true, onNavigate, ...props }));
  });
  await act(async () => { await vi.advanceTimersByTimeAsync(700); });
}
const card = () => document.querySelector<HTMLElement>(".guide-card");
const text = () => card()?.textContent ?? "";
const press = async (label: string) => {
  const button = [...document.querySelectorAll<HTMLButtonElement>(".guide button")].find((item) => item.textContent === label);
  if (!button) throw new Error(`no button ${label}`);
  await act(async () => button.click());
};

describe("GuideRunner", () => {
  it("walks a guest through the home guide and remembers it", async () => {
    await mount();
    expect(text()).toContain("欢迎来到 WaveCast");
    await press("开始");
    expect(text()).toContain("先从这几档精选里挑一个");
    await press("下一步");
    expect(text()).toContain("按电台风格调频");
    await press("下一步");
    expect(text()).toContain("想听什么，直接说出来");
    await press("下一步");
    expect(text()).toContain("登录后，推荐更懂你");
    expect(readSeenGuides()).toEqual({});
    await press("以后再说");
    expect(card()).toBeNull();
    expect(readSeenGuides()).toEqual({ "home-intro": 1 });
    expect(onNavigate).not.toHaveBeenCalled();
  });

  it("sends the guest to sign in from the last step", async () => {
    await mount();
    for (const label of ["开始", "下一步", "下一步", "下一步"]) await press(label);
    await press("登录");
    expect(onNavigate).toHaveBeenCalledWith("/account");
    expect(readSeenGuides()["home-intro"]).toBe(1);
  });

  it("can be skipped at any step, and then does not come back", async () => {
    await mount();
    await press("跳过");
    expect(card()).toBeNull();
    expect(readSeenGuides()["home-intro"]).toBe(1);
    await act(async () => root.unmount());
    root = createRoot(host);
    await mount();
    expect(card()).toBeNull();
  });

  it("shows a signed-in person their own wording and no sign-in step", async () => {
    await mount({ signedIn: true });
    await press("开始");
    expect(text()).toContain("按你的口味准备的节目");
    for (const label of ["下一步", "下一步"]) await press(label);
    // nav-tune was the last step they see.
    expect(card()).not.toBeNull();
    await press("知道了");
    expect(card()).toBeNull();
  });

  it("then shows the unlocked card on the next visit to a person who saw the guide as a guest", async () => {
    window.localStorage.setItem("wavecast-guides-seen-v1", JSON.stringify({ "home-intro": 1 }));
    await mount({ signedIn: true });
    expect(text()).toContain("为你推荐已解锁");
    expect(document.querySelector(".guide-skip")).toBeNull();
    await press("知道了");
    expect(readSeenGuides()).toEqual({ "home-intro": 1, "home-unlocked": 1 });
  });

  it("skips a step whose element is not on the page", async () => {
    document.querySelector('[data-guide="home-stations"]')!.remove();
    await mount();
    await press("开始");
    await press("下一步");
    expect(text()).toContain("想听什么，直接说出来");
  });

  it("waits while something else is open, and until the page is ready", async () => {
    const release = registerOverlay(() => undefined);
    await mount();
    expect(card()).toBeNull();
    release();
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(text()).toContain("欢迎来到 WaveCast");
  });

  it("does not start before the page is ready or the session is known", async () => {
    await mount({ ready: false });
    expect(card()).toBeNull();
    await act(async () => root.render(createElement(GuideRunner, { trigger: "home", signedIn: null, ready: true, onNavigate })));
    await act(async () => { await vi.advanceTimersByTimeAsync(1500); });
    expect(card()).toBeNull();
  });

  it("gives way when another one-off prompt already holds the visit", async () => {
    window.sessionStorage.setItem("wavecast-visit-prompt-v1", "install");
    await mount();
    expect(card()).toBeNull();
    expect(readSeenGuides()).toEqual({});
  });

  it("holds the visit so the install prompt does not take it", async () => {
    await mount({ ready: false });
    expect(window.sessionStorage.getItem("wavecast-visit-prompt-v1")).toBe("guide");
  });

  it("points out the round 准备完整版 button on the tune page, the one thing the 电台指南 leaves", async () => {
    await mount({ trigger: "tune" });
    expect(text()).toContain("准备完整版");
    expect(document.querySelector(".guide")?.textContent).not.toContain("下一步");
    await press("知道了");
    expect(readSeenGuides()).toEqual({ "tune-full": 1 });
  });

  it("closes on Escape as a skip", async () => {
    await mount();
    await act(async () => { window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })); });
    expect(card()).toBeNull();
    expect(readSeenGuides()["home-intro"]).toBe(1);
  });
});
