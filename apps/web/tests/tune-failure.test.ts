import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
vi.mock("../lib/overlay-stack", () => ({ useOverlay: vi.fn() }));
(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
import { TuningInScreen } from "../components/tune/tuning-in";
import { ApiRequestError } from "../lib/api";
import { failureCanRetry } from "../lib/friendly-error";
import { STATIONS } from "../lib/stations";

it("treats 422 as a request that retrying cannot fix, and everything else as retryable", () => {
  expect(failureCanRetry(new ApiRequestError("没能找到可以播放的开场歌", 422))).toBe(false);
  expect(failureCanRetry(new ApiRequestError("音乐服务暂时不太稳定", 503))).toBe(true);
  expect(failureCanRetry(new ApiRequestError("Program proposal generation failed", 502))).toBe(true);
  expect(failureCanRetry(new ApiRequestError("x", 429))).toBe(true);
  expect(failureCanRetry(new Error("network down"))).toBe(true);
  expect(failureCanRetry(undefined)).toBe(true);
});

let root: Root;
let host: HTMLDivElement;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

async function renderScreen(props: { error: string | null; retryable?: boolean }) {
  const onCancel = vi.fn();
  const onRetry = vi.fn();
  await act(async () =>
    root.render(
      createElement(TuningInScreen, {
        station: STATIONS[0],
        steps: [{ label: "正在理解你想听的", done: false }],
        error: props.error,
        retryable: props.retryable,
        onCancel,
        onRetry,
      }),
    ),
  );
  return { onCancel, onRetry };
}

function button(text: string) {
  return [...document.querySelectorAll(".tuning-error button")].find((node) => node.textContent === text) as
    | HTMLButtonElement
    | undefined;
}

it("offers 重试 for a retryable failure", async () => {
  const { onCancel, onRetry } = await renderScreen({ error: "音乐服务暂时不太稳定，请稍后再试。" });
  expect(document.querySelector(".tuning-error")?.textContent).toContain("稍后再试");
  expect(button("换个说法")).toBeUndefined();
  await act(async () => button("重试")!.click());
  expect(onRetry).toHaveBeenCalledTimes(1);
  expect(onCancel).not.toHaveBeenCalled();
});

it("offers 换个说法 instead of 重试 when the failure is deterministic", async () => {
  const { onCancel, onRetry } = await renderScreen({
    error: "没能找到可以播放的开场歌。可能因为版权暂时没有合适的音源。",
    retryable: false,
  });
  expect(document.querySelector(".tuning-error")?.textContent).toContain("版权");
  expect(button("重试")).toBeUndefined();
  await act(async () => button("换个说法")!.click());
  expect(onCancel).toHaveBeenCalledTimes(1);
  expect(onRetry).not.toHaveBeenCalled();
});

it("shows no error block when there is no error", async () => {
  await renderScreen({ error: null });
  expect(document.querySelector(".tuning-error")).toBeNull();
});
