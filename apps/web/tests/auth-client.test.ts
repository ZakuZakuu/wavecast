import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { tokenRequest } = vi.hoisted(() => ({ tokenRequest: vi.fn() }));

vi.mock("better-auth/react", () => ({
  createAuthClient: () => ({ token: tokenRequest }),
}));
vi.mock("better-auth/client/plugins", () => ({ jwtClient: () => ({}) }));

import {
  clearApiAuthToken,
  getApiAuthToken,
  getApiAuthTokenForUser,
} from "../lib/auth-client";

describe("API auth token cache", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-25T00:00:00Z"));
    tokenRequest.mockReset();
    clearApiAuthToken();
  });

  afterEach(() => {
    clearApiAuthToken();
    vi.useRealTimers();
  });

  it("negative-caches guest token failures for the short backoff", async () => {
    tokenRequest.mockResolvedValue({ data: null, error: { status: 401 } });

    await expect(getApiAuthToken()).resolves.toBeUndefined();
    await expect(getApiAuthToken()).resolves.toBeUndefined();
    expect(tokenRequest).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(30_001);
    await expect(getApiAuthToken()).resolves.toBeUndefined();
    expect(tokenRequest).toHaveBeenCalledTimes(2);
  });

  it("falls back to guest when the auth client throws", async () => {
    tokenRequest.mockRejectedValue(new Error("Request failed"));

    await expect(getApiAuthToken()).resolves.toBeUndefined();
    await expect(getApiAuthToken()).resolves.toBeUndefined();
    expect(tokenRequest).toHaveBeenCalledTimes(1);
  });

  it("falls back to guest for non-numeric auth service errors", async () => {
    tokenRequest.mockResolvedValue({
      data: null,
      error: { status: "SERVICE_UNAVAILABLE" },
    });

    await expect(getApiAuthToken()).resolves.toBeUndefined();
    expect(tokenRequest).toHaveBeenCalledTimes(1);
  });

  it("binds an authenticated request token to the expected JWT subject", async () => {
    const payload = btoa(JSON.stringify({ sub: "account-two", exp: Date.now() / 1000 + 3600 }))
      .replace(/=/g, "")
      .replace(/\+/g, "-")
      .replace(/\//g, "_");
    const token = `header.${payload}.signature`;
    tokenRequest.mockResolvedValue({ data: { token }, error: null });

    await expect(getApiAuthTokenForUser("account-one"))
      .rejects.toThrow("Could not verify the signed-in library identity");
    await expect(getApiAuthTokenForUser("account-two")).resolves.toBe(token);
    expect(tokenRequest).toHaveBeenCalledTimes(1);
  });

  it("clears the guest negative cache when the session changes", async () => {
    tokenRequest.mockResolvedValueOnce({ data: null, error: { status: 401 } });
    await expect(getApiAuthToken()).resolves.toBeUndefined();

    clearApiAuthToken();
    const payload = btoa(JSON.stringify({ exp: Date.now() / 1000 + 3600 }))
      .replace(/=/g, "")
      .replace(/\+/g, "-")
      .replace(/\//g, "_");
    const token = `header.${payload}.signature`;
    tokenRequest.mockResolvedValueOnce({ data: { token }, error: null });

    await expect(getApiAuthToken()).resolves.toBe(token);
    expect(tokenRequest).toHaveBeenCalledTimes(2);
  });
});
