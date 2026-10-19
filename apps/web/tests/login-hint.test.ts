import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const session = { data: null as null | { user: { id: string } } };
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("../lib/auth-client", () => ({ authClient: { useSession: () => session } }));
import { LoginNudge } from "../components/login-nudge";
import { loginNudgeSnoozedUntil, requestLoginHint } from "../lib/login-nudge";

let root: Root;
let host: HTMLDivElement;
beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  session.data = null;
  vi.stubGlobal("matchMedia", () => ({ matches: true }));
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

const hint = { title: "登录后才能换一批", note: "登录后可以获得完整推荐" };
async function mount() {
  await act(async () => root.render(createElement(LoginNudge, { hidden: false })));
}

it("shows a hint the listener asked for at once, with its own words", async () => {
  await mount();
  expect(host.textContent).toBe("");
  await act(async () => requestLoginHint(hint));
  expect(host.textContent).toContain("登录后才能换一批");
  expect(host.textContent).toContain("登录后可以获得完整推荐");
});

it("does not snooze the one-off card when an asked-for hint is dismissed", async () => {
  await mount();
  await act(async () => requestLoginHint(hint));
  await act(async () => [...host.querySelectorAll("button")].find((node) => node.textContent === "以后再说")!.click());
  expect(host.textContent).toBe("");
  expect(loginNudgeSnoozedUntil()).toBe(0);
});

it("stays quiet for a signed-in listener", async () => {
  session.data = { user: { id: "u1" } };
  await mount();
  await act(async () => requestLoginHint(hint));
  expect(host.textContent).toBe("");
});
