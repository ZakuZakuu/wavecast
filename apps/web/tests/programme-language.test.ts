import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("../lib/auth-client", () => ({
  getApiAuthToken: vi.fn(async () => undefined),
  getApiAuthTokenForUser: vi.fn(),
  getApiAuthUserId: vi.fn(async () => undefined),
}));

import { PROGRAMME_LANGUAGE } from "../components/tune/use-tune-start";
import { api } from "../lib/api";

const originalFetch = globalThis.fetch;

beforeEach(() => {
  localStorage.setItem("wavecast-anonymous-listener", "test-listener");
  globalThis.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ proposals: [] }) });
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  localStorage.clear();
});

it("asks for a Chinese programme because the interface is Chinese", () => {
  expect(PROGRAMME_LANGUAGE).toBe("zh-CN");
});

it("sends the chosen programme language with the proposal request", async () => {
  await api.createProgramProposals({ prompt: "late night synth drive", duration_intent: "STANDARD", output_language: PROGRAMME_LANGUAGE });

  const [, init] = vi.mocked(globalThis.fetch).mock.calls[0];
  expect(JSON.parse(String(init?.body))).toMatchObject({
    prompt: "late night synth drive",
    output_language: "zh-CN",
    count: 1,
  });
});

it("sends the tuned station with the proposal request", async () => {
  await api.createProgramProposals({
    prompt: "睡前听的安静音乐",
    duration_intent: "STANDARD",
    station: "night",
  });

  const [, init] = vi.mocked(globalThis.fetch).mock.calls[0];
  expect(JSON.parse(String(init?.body))).toMatchObject({ station: "night" });
});
