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

const stepChange = vi.fn();
async function render() {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root.render(createElement(EmailLogin, { disabled: false, onSuccess: success, onBusyChange: busyChange, onStepChange: stepChange })));
}
/** A reload / iOS discarding the page: everything in memory goes, sessionStorage stays. */
async function reload() {
  await act(async () => root.unmount());
  host.remove();
  await render();
}
const STORE_KEY = "wavecast-email-login-v1";
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
    window.sessionStorage.clear();
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

  describe("recovering after a reload", () => {
    async function sendCode() {
      await render();
      await input("login-email", "Listener@Example.com");
      await submit();
    }

    it("returns to the code step with the remaining cooldown and does not send again", async () => {
      await sendCode();
      await act(async () => vi.advanceTimersByTime(20_000));
      await reload();
      expect(mocks.send).toHaveBeenCalledOnce();
      expect(host.querySelector("#login-otp")).not.toBeNull();
      expect(host.textContent).toContain("listener@example.com");
      expect(button("40 秒后重发").disabled).toBe(true);
      expect(stepChange).toHaveBeenLastCalledWith(true);
      await input("login-otp", "654321");
      await submit();
      expect(mocks.signIn).toHaveBeenCalledWith({ email: "listener@example.com", otp: "654321" });
      expect(mocks.send).toHaveBeenCalledOnce();
    });

    it("stores the address, step and times only: never the code or a credential", async () => {
      await sendCode();
      await input("login-otp", "123456");
      const stored = window.sessionStorage.getItem(STORE_KEY)!;
      expect(Object.keys(JSON.parse(stored)).sort()).toEqual(["email", "expiresAt", "resendAt", "step"]);
      expect(stored).not.toContain("123456");
      expect(window.sessionStorage.length).toBe(1);
      expect(window.localStorage.getItem(STORE_KEY)).toBeNull();
    });

    it("forgets the flow on a successful login", async () => {
      await sendCode();
      await input("login-otp", "123456");
      await submit();
      expect(success).toHaveBeenCalledOnce();
      expect(window.sessionStorage.getItem(STORE_KEY)).toBeNull();
    });

    it("forgets the flow when the listener picks another email, keeping the address to edit", async () => {
      await sendCode();
      await act(async () => button("换个邮箱").click());
      expect(window.sessionStorage.getItem(STORE_KEY)).toBeNull();
      expect(host.querySelector<HTMLInputElement>("#login-email")!.value).toBe("listener@example.com");
      await reload();
      expect(host.querySelector("#login-email")).not.toBeNull();
      expect(host.querySelector("#login-otp")).toBeNull();
    });

    it("lets an expired flow go: back to the email step, nothing stored", async () => {
      await sendCode();
      const stored = JSON.parse(window.sessionStorage.getItem(STORE_KEY)!);
      vi.setSystemTime(stored.expiresAt + 1);
      await reload();
      expect(host.querySelector("#login-email")).not.toBeNull();
      expect(host.querySelector<HTMLInputElement>("#login-email")!.value).toBe("");
      expect(window.sessionStorage.getItem(STORE_KEY)).toBeNull();
      expect(mocks.send).toHaveBeenCalledOnce();
    });

    it.each([
      ["not json", "{oops"],
      ["wrong shape", JSON.stringify({ email: 5, step: "code" })],
      ["unknown step", JSON.stringify({ email: "a@b.co", step: "done", resendAt: 1, expiresAt: Date.now() + 1000 })],
      ["a lifetime beyond the code's", JSON.stringify({ email: "a@b.co", step: "code", resendAt: 1, expiresAt: Date.now() + 3_600_000 })],
    ])("ignores a damaged record (%s)", async (_name, value) => {
      window.sessionStorage.setItem(STORE_KEY, value);
      await render();
      expect(host.querySelector("#login-email")).not.toBeNull();
      expect(host.querySelector("#login-otp")).toBeNull();
      expect(mocks.send).not.toHaveBeenCalled();
    });

    it("keeps the cooldown after a rate-limited send, still on the email step", async () => {
      mocks.send.mockResolvedValue({ error: { status: 429 } });
      await sendCode();
      expect(host.querySelector('[role="alert"]')?.textContent).toBe("操作有点频繁，请稍等一分钟再试。");
      await reload();
      expect(host.querySelector<HTMLInputElement>("#login-email")!.value).toBe("listener@example.com");
      expect(host.textContent).toContain("60 秒后可发送");
      expect(mocks.send).toHaveBeenCalledOnce();
    });

    it("still works when sessionStorage is unavailable", async () => {
      const blocked = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("denied"); });
      const blockedSet = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("denied"); });
      try {
        await sendCode();
        expect(host.querySelector("#login-otp")).not.toBeNull();
        await input("login-otp", "123456");
        await submit();
        expect(success).toHaveBeenCalledOnce();
      } finally {
        blocked.mockRestore();
        blockedSet.mockRestore();
      }
    });
  });
});
