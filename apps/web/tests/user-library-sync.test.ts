import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  getUserId: vi.fn<() => Promise<string | undefined>>(),
  merge: vi.fn<(value: unknown) => Promise<unknown>>(),
  getLibrary: vi.fn<() => Promise<unknown>>(),
}));

vi.mock("../lib/auth-client", () => ({ getApiAuthUserId: mocks.getUserId }));
vi.mock("../lib/api", () => ({
  api: {
    mergeMyLibrary: mocks.merge,
    myLibrary: mocks.getLibrary,
  },
}));

import {
  emptyUserLibrary,
  readUserLibrary,
  syncAuthenticatedLibrary,
  useGuestLibraryIdentity,
} from "../lib/user-library";

describe("authenticated library cache isolation", () => {
  beforeEach(() => {
    localStorage.clear();
    useGuestLibraryIdentity();
    mocks.getUserId.mockReset();
    mocks.merge.mockReset();
    mocks.getLibrary.mockReset();
  });

  it("merges guest state before reading canonical account state and retains guest cache", async () => {
    const guest = { ...emptyUserLibrary(), favoriteSeedIds: ["guest-favorite"] };
    localStorage.setItem("wavecast-user-library-v1", JSON.stringify(guest));
    const canonical = { ...emptyUserLibrary(), favoriteSeedIds: ["canonical-favorite"] };
    mocks.getUserId.mockResolvedValue("account-one");
    mocks.merge.mockResolvedValue(canonical);
    mocks.getLibrary.mockResolvedValue(canonical);

    await syncAuthenticatedLibrary();

    expect(mocks.merge).toHaveBeenCalledTimes(1);
    expect(mocks.merge).toHaveBeenCalledWith(guest);
    expect(readUserLibrary().favoriteSeedIds).toEqual(["canonical-favorite"]);
    expect(JSON.parse(localStorage.getItem("wavecast-user-library-v1") ?? "{}"))
      .toEqual(guest);
    expect(localStorage.getItem("wavecast-user-library-v1:account:account-one"))
      .not.toBeNull();
  });

  it("does not re-merge stale guest favorites after the account deletes them", async () => {
    const guest = { ...emptyUserLibrary(), favoriteSeedIds: ["old-guest-favorite"] };
    localStorage.setItem("wavecast-user-library-v1", JSON.stringify(guest));
    mocks.getUserId.mockResolvedValue("account-one");
    mocks.merge.mockResolvedValue(emptyUserLibrary());
    mocks.getLibrary.mockResolvedValue(emptyUserLibrary());
    await syncAuthenticatedLibrary();

    localStorage.setItem(
      "wavecast-user-library-v1:account:account-one",
      JSON.stringify(emptyUserLibrary()),
    );
    mocks.merge.mockClear();
    await syncAuthenticatedLibrary();

    expect(mocks.merge).not.toHaveBeenCalled();
    expect(readUserLibrary().favoriteSeedIds).toEqual([]);
  });

  it("does not carry one account cache into another account", async () => {
    mocks.getUserId.mockResolvedValue("account-one");
    mocks.merge.mockResolvedValue(emptyUserLibrary());
    mocks.getLibrary.mockResolvedValue({
      ...emptyUserLibrary(),
      favoriteSeedIds: ["account-one-favorite"],
    });
    await syncAuthenticatedLibrary();

    mocks.getUserId.mockResolvedValue("account-two");
    mocks.getLibrary.mockResolvedValue({
      ...emptyUserLibrary(),
      favoriteSeedIds: ["account-two-favorite"],
    });
    await syncAuthenticatedLibrary();

    expect(readUserLibrary().favoriteSeedIds).toEqual(["account-two-favorite"]);
    expect(localStorage.getItem("wavecast-user-library-v1:account:account-one"))
      .not.toBeNull();
  });

  it("returns to the original guest cache on logout", async () => {
    const guest = { ...emptyUserLibrary(), favoriteSeedIds: ["guest-only"] };
    localStorage.setItem("wavecast-user-library-v1", JSON.stringify(guest));
    mocks.getUserId.mockResolvedValue("account-one");
    mocks.merge.mockResolvedValue(emptyUserLibrary());
    mocks.getLibrary.mockResolvedValue({
      ...emptyUserLibrary(),
      favoriteSeedIds: ["account-only"],
    });
    await syncAuthenticatedLibrary();

    useGuestLibraryIdentity();

    expect(readUserLibrary().favoriteSeedIds).toEqual(["guest-only"]);
  });
});
