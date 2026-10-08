import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ send: vi.fn(), signIn: vi.fn() }));
vi.mock("../lib/auth-client", () => ({ authClient: {
  emailOtp: { sendVerificationOtp: mocks.send },
  signIn: { emailOtp: mocks.signIn },
} }));
import { EmailLogin } from "../components/account/email-login";

let host: HTMLDivElement;
let root: Root;
const success = vi.fn();
const busyChange = vi.fn();

async function render() {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root.render(createElement(EmailLogin, { disabled: false, onSuccess: success, onBusyChange: busyChange })));
}
async function input(id: string, value: string) {
  const target = host.querySelector<HTMLInputElement>(`#${id}`)!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(target, value);
    target.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
async function submit() {
  await act(async () => host.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
}
function button(text: string) {
  return [...host.querySelectorAll("button")].find((node) => node.textContent === text)!;
}

describe("email code login UI", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    mocks.send.mockResolvedValue({ data: { success: true }, error: null });
    mocks.signIn.mockResolvedValue({ data: {}, error: null });
    (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  });
  afterEach(async () => {
    if (root) await act(async () => root.unmount());
    host?.remove();
    vi.useRealTimers();
  });

  it("normalizes the email, focuses the autofill code input, blocks resends, then logs in", async () => {
    await render();
    await input("login-email", "Listener@Example.com");
    await submit();
    expect(mocks.send).toHaveBeenCalledWith({ email: "listener@example.com", type: "sign-in" });
    expect(document.activeElement?.id).toBe("login-otp");
    expect(button("60 秒后重发").disabled).toBe(true);
    await input("login-otp", "123456");
    await submit();
    expect(mocks.signIn).toHaveBeenCalledWith({ email: "listener@example.com", otp: "123456" });
    expect(success).toHaveBeenCalledOnce();
    expect(busyChange).toHaveBeenLastCalledWith(false);
  });

  it("lets users resend after a minute and keeps a wrong-code error recoverable", async () => {
    await render();
    await input("login-email", "listener@example.com");
    await submit();
    await act(async () => vi.advanceTimersByTime(60_000));
    await act(async () => button("重新发送").click());
    expect(mocks.send).toHaveBeenCalledTimes(2);
    mocks.signIn.mockResolvedValue({ error: { code: "INVALID_OTP" } });
    await input("login-otp", "123456");
    await submit();
    expect(host.querySelector('[role="alert"]')?.textContent).toBe("验证码不正确，请检查后再试。");
    expect(success).not.toHaveBeenCalled();
    await act(async () => button("换个邮箱").click());
    expect(host.querySelector("#login-email")).not.toBeNull();
    expect(host.querySelector('[role="alert"]')).toBeNull();
  });

  it("does not claim the email was sent when the provider fails", async () => {
    mocks.send.mockResolvedValue({ error: { status: 503, message: "private upstream details" } });
    await render();
    await input("login-email", "listener@example.com");
    await submit();
    expect(host.querySelector("#login-otp")).toBeNull();
    expect(host.querySelector('[role="alert"]')?.textContent).toBe("验证码暂时没发出去，请稍后再试。");
    expect(host.textContent).not.toContain("private upstream details");
  });
});
