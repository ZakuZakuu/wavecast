import { act, createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createRoot, type Root } from "react-dom/client";

const mocks = vi.hoisted(() => ({
  session: { data: { user: { id: "user-1" } }, isPending: false },
  router: { replace: vi.fn() },
  api: {
    userPreferences: vi.fn(),
    saveUserPreferences: vi.fn(),
  },
}));

vi.mock("../lib/api", () => ({ api: mocks.api }));
vi.mock("../lib/auth-client", () => ({
  authClient: { useSession: () => mocks.session },
}));
vi.mock("next/navigation", () => ({ useRouter: () => mocks.router }));
vi.mock("../components/app-shell", () => ({
  AppShell: ({ children }: { children: ReactNode }) => children,
}));

import { OnboardingPage } from "../components/onboarding-page";

const initialPreferences = {
  user_id: "user-1",
  genres: [],
  artists: [],
  moods: [],
  contexts: [],
  discovery_level: "BALANCED" as const,
  onboarding_completed: false,
  updated_at: "2026-09-25T00:00:00Z",
};

let host: HTMLDivElement;
let root: Root;

async function renderPage() {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => {
    root.render(createElement(OnboardingPage));
    await Promise.resolve();
  });
}

function button(label: string): HTMLButtonElement {
  const target = [...host.querySelectorAll("button")].find((item) => item.textContent === label);
  if (!target) throw new Error(`button not found: ${label}`);
  return target;
}

describe("first-login onboarding", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.session = { data: { user: { id: "user-1" } }, isPending: false };
    mocks.api.userPreferences.mockResolvedValue(initialPreferences);
    mocks.api.saveUserPreferences.mockResolvedValue({
      ...initialPreferences,
      onboarding_completed: true,
    });
    (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean })
      .IS_REACT_ACT_ENVIRONMENT = true;
  });

  afterEach(async () => {
    if (root) await act(async () => root.unmount());
    host?.remove();
  });

  it("saves selected vibe preferences and completes onboarding", async () => {
    await renderPage();
    await act(async () => button("City Pop").click());
    await act(async () => button("Late Night").click());
    await act(async () => button("多发现新声音").click());
    await act(async () => {
      button("完成").click();
      await Promise.resolve();
    });

    expect(mocks.api.userPreferences).toHaveBeenCalledWith("user-1");
    expect(mocks.api.saveUserPreferences).toHaveBeenCalledWith({
      genres: ["City Pop"],
      artists: [],
      moods: ["Late Night"],
      contexts: [],
      discovery_level: "ADVENTUROUS",
      onboarding_completed: true,
    }, "user-1");
    expect(mocks.router.replace).toHaveBeenCalledWith("/");
  });

  it("allows skipping and persists completion without preferences", async () => {
    await renderPage();
    await act(async () => {
      button("跳过，先去听").click();
      await Promise.resolve();
    });

    expect(mocks.api.saveUserPreferences).toHaveBeenCalledWith({
      genres: [],
      artists: [],
      moods: [],
      contexts: [],
      discovery_level: "BALANCED",
      onboarding_completed: true,
    }, "user-1");
    expect(mocks.router.replace).toHaveBeenCalledWith("/");
  });

  it("does not show onboarding again after preferences are persisted", async () => {
    mocks.api.userPreferences.mockResolvedValue({
      ...initialPreferences,
      onboarding_completed: true,
    });
    await renderPage();

    expect(mocks.router.replace).toHaveBeenCalledWith("/");
    expect(host.textContent).not.toContain("从你喜欢的声音开始");
  });
});
