import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
vi.mock("../lib/overlay-stack", () => ({ useOverlay: vi.fn() }));
(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
import { BrowserGuidance } from "../components/browser-guidance";

let root: Root;
let host: HTMLDivElement;
const writeText = vi.fn();
beforeEach(() => {
  sessionStorage.clear();
  vi.spyOn(navigator, "userAgent", "get").mockReturnValue("Mozilla/5.0 (iPhone) Mobile MicroMessenger/8.0");
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
  writeText.mockReset();
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); });
async function render() { await act(async () => root.render(createElement(BrowserGuidance))); }
async function click(text: string) {
  const button = [...document.querySelectorAll("button")].find((node) => node.textContent === text);
  expect(button).toBeDefined(); await act(async () => button!.click());
}
it("reuses the installation card and copies the current programme link", async () => {
  await render();
  expect(document.querySelector(".install-card")?.textContent).toContain("推荐用 Safari 收听");
  writeText.mockResolvedValue(undefined); await click("复制当前链接");
  expect(writeText).toHaveBeenCalledWith(window.location.href);
  expect(document.body.textContent).toContain("已复制链接");
});
it("offers manual copy when permission fails", async () => {
  await render(); writeText.mockRejectedValue(new Error("denied")); await click("复制当前链接");
  expect(document.querySelector("input")?.value).toBe(window.location.href);
  expect(document.body.textContent).toContain("请手动复制");
});
it("allows continuing without re-opening on the same visit", async () => {
  await render(); await click("继续体验");
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 200)); });
  expect(document.querySelector('[role="dialog"]')).toBeNull();
  await act(async () => root.unmount()); root = createRoot(host); await render();
  expect(document.querySelector('[role="dialog"]')).toBeNull();
});
