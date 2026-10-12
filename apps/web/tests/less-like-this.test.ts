import { beforeEach, describe, expect, it } from "vitest";

import { lessLikeThisArtists, recordLessLikeThis, removeLessLikeThisArtist, syncLessLikeThis } from "../lib/listener-feedback";
import { tasteContext } from "../lib/taste";

function installStorage() {
  const data = new Map<string, string>();
  const storage = {
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => void data.set(key, value),
    removeItem: (key: string) => void data.delete(key),
  };
  Object.defineProperty(globalThis, "window", { value: { localStorage: storage }, configurable: true });
}

const mark = (artist: string | null, trackRef: string) =>
  recordLessLikeThis({ trackRef, title: "t", artist, episodeId: "e" });

describe("少放这类", () => {
  beforeEach(installStorage);

  it("lists each artist once, newest first, and skips tracks without one", () => {
    mark("Mogwai", "a");
    mark(null, "b");
    mark("Perfume", "c");
    mark("mogwai", "d");
    expect(lessLikeThisArtists()).toEqual(["mogwai", "Perfume"]);
  });

  it("sends each artist to the account once, oldest first, and retries only what failed", async () => {
    mark("Mogwai", "a");
    mark("Perfume", "b");
    const sent: string[] = [];
    await syncLessLikeThis("user-1", async (artist) => void sent.push(artist));
    expect(sent).toEqual(["Mogwai", "Perfume"]);

    await syncLessLikeThis("user-1", async (artist) => void sent.push(artist));
    expect(sent).toHaveLength(2);

    mark("Explosions in the Sky", "c");
    let failing = true;
    await syncLessLikeThis("user-1", async (artist) => {
      if (failing) throw new Error("offline");
      sent.push(artist);
    });
    expect(sent).toHaveLength(2);
    failing = false;
    await syncLessLikeThis("user-1", async (artist) => void sent.push(artist));
    expect(sent.at(-1)).toBe("Explosions in the Sky");
  });

  it("forgets an artist on this device, whatever its capitalisation", () => {
    mark("Mogwai", "a");
    mark("Perfume", "b");
    removeLessLikeThisArtist(" mogwai ");
    expect(lessLikeThisArtists()).toEqual(["Perfume"]);
  });

  it("adds the avoided artists to the taste text, even when there is nothing else", () => {
    expect(tasteContext(null, [])).toBeUndefined();
    expect(tasteContext(null, ["Mogwai", "Perfume"])).toBe("少放：Mogwai、Perfume");
    const taste = { genres: ["后摇"], artists: "", moments: [], updatedAt: 0 };
    expect(tasteContext(taste, ["Mogwai"])).toBe("爱听：后摇；少放：Mogwai");
  });

  it("keeps the avoided artists whole when the taste text is long", () => {
    const taste = { genres: [], artists: "歌".repeat(1200), moments: [], updatedAt: 0 };
    const text = tasteContext(taste, ["Mogwai"]) ?? "";
    expect(text.length).toBeLessThanOrEqual(1000);
    expect(text.endsWith("少放：Mogwai")).toBe(true);
  });
});
