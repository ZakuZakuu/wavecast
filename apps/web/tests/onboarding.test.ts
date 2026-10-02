import { act, createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createRoot, type Root } from "react-dom/client";

const mocks = vi.hoisted(() => ({
  session: { data: { user: { id: "user-1" } } as { user: { id: string } } | null, isPending: false },
  api: {
    userPreferences: vi.fn(),
    saveUserPreferences: vi.fn(),
  },
}));

vi.mock("../lib/api", () => ({ api: mocks.api }));
vi.mock("../lib/auth-client", () => ({
  authClient: { useSession: () => mocks.session },
}));

import { backendGenres, parseArtists, preferenceUpdate } from "../lib/onboarding";
import { OnboardingSheet } from "../components/onboarding/onboarding-sheet";

const initialPreferences = {
  user_id: "user-1",
  genres: [],
  artists: [],
  moods: ["Chill" as const],
  contexts: [],
  discovery_level: "BALANCED" as const,
  onboarding_completed: false,
  updated_at: "2026-09-25T00:00:00Z",
};

let host: HTMLDivElement;
let root: Root;
const onFinished = vi.fn();

async function render() {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => {
    root.render(createElement(OnboardingSheet, { onFinished }));
    await Promise.resolve();
  });
  await act(async () => { await Promise.resolve(); });
}

function button(label: string): HTMLButtonElement {
  const target = [...document.querySelectorAll("button")].find((item) => item.textContent === label);
  if (!target) throw new Error(`button not found: ${label}`);
  return target;
}

describe("onboarding mapping", () => {
  it("maps design genres onto the backend enum and parses artists", () => {
    expect(backendGenres(["华语流行", "R&B", "爵士", "Hip-hop", "氛围"])).toEqual(["R&B", "Jazz", "Hip-Hop"]);
    expect(parseArtists("方大同、坂本龙一, 方大同")).toEqual(["方大同", "坂本龙一"]);
    expect(preferenceUpdate(null, null)).toMatchObject({ genres: [], onboarding_completed: true });
  });
});

describe("first-login onboarding sheet", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    mocks.session = { data: { user: { id: "user-1" } }, isPending: false };
    mocks.api.userPreferences.mockResolvedValue(initialPreferences);
    mocks.api.saveUserPreferences.mockResolvedValue({ ...initialPreferences, onboarding_completed: true });
    (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  });

  afterEach(async () => {
    if (root) await act(async () => root.unmount());
    host?.remove();
  });

  it("saves both steps, keeps existing moods and completes onboarding once", async () => {
    await render();
    await act(async () => button("City Pop").click());
    await act(async () => button("爵士").click());
    expect(button("继续（已选 2 个）")).toBeTruthy();
    await act(async () => button("继续（已选 2 个）").click());
    await act(async () => button("睡前").click());
    await act(async () => {
      button("完成").click();
      await Promise.resolve();
    });

    expect(mocks.api.saveUserPreferences).toHaveBeenCalledWith({
      genres: ["City Pop", "Jazz"],
      artists: [],
      moods: ["Chill"],
      contexts: ["睡前"],
      discovery_level: "BALANCED",
      onboarding_completed: true,
    }, "user-1");
    expect(JSON.parse(window.localStorage.getItem("wavecast-taste-v1")!).genres).toEqual(["City Pop", "爵士"]);
    expect(onFinished).toHaveBeenCalled();
    expect(window.localStorage.getItem("wavecast-onboarding-done:user-1")).toBe("1");
  });

  it("allows skipping and persists completion without new preferences", async () => {
    await render();
    await act(async () => {
      button("跳过").click();
      await Promise.resolve();
    });
    expect(mocks.api.saveUserPreferences).toHaveBeenCalledWith({
      genres: [],
      artists: [],
      moods: ["Chill"],
      contexts: [],
      discovery_level: "BALANCED",
      onboarding_completed: true,
    }, "user-1");
  });

  it("does not show again once completed, and never for guests", async () => {
    mocks.api.userPreferences.mockResolvedValue({ ...initialPreferences, onboarding_completed: true });
    await render();
    expect(document.body.textContent).not.toContain("平时爱听什么？");
    expect(onFinished).toHaveBeenCalled();
    await act(async () => root.unmount());

    mocks.session = { data: null, isPending: false };
    await render();
    expect(mocks.api.userPreferences).toHaveBeenCalledTimes(1);
    expect(document.body.textContent).not.toContain("平时爱听什么？");
  });
});
