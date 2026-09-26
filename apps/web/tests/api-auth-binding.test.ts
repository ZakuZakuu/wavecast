import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  token: vi.fn<() => Promise<string | undefined>>(),
  tokenForUser: vi.fn<(userId: string) => Promise<string>>(),
}));

vi.mock("../lib/auth-client", () => ({
  getApiAuthToken: mocks.token,
  getApiAuthTokenForUser: mocks.tokenForUser,
}));

import { api } from "../lib/api";

describe("authenticated Library request identity binding", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    localStorage.setItem("wavecast-anonymous-listener", "test-listener");
    mocks.token.mockReset();
    mocks.tokenForUser.mockReset();
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true }),
    });
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    localStorage.clear();
  });

  it("uses a token verified for the expected account on the same request", async () => {
    mocks.tokenForUser.mockResolvedValue("account-one-token");

    await api.mergeMyLibrary({ createdProgramIds: ["proposal-a"] }, "account-one");

    expect(mocks.tokenForUser).toHaveBeenCalledWith("account-one");
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
    const [, init] = vi.mocked(globalThis.fetch).mock.calls[0];
    expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer account-one-token");
  });

  it("does not send the Library payload if token identity verification fails", async () => {
    mocks.tokenForUser.mockRejectedValue(new Error("Could not verify the signed-in library identity"));

    await expect(api.mergeMyLibrary({ recentPrograms: [{ title: "private" }] }, "account-one"))
      .rejects.toThrow("Could not verify the signed-in library identity");

    expect(globalThis.fetch).not.toHaveBeenCalled();
  });
});
