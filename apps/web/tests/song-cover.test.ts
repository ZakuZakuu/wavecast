import { describe, expect, it } from "vitest";

import { coverInFront, rememberCoverChoice, rememberedCoverChoice, songCoverSrc } from "../lib/song-cover";

describe("songCoverSrc", () => {
  it("asks NetEase for the size the player needs", () => {
    expect(songCoverSrc("https://p1.music.126.net/abc/123.jpg")).toBe("https://p1.music.126.net/abc/123.jpg?param=600y600");
    expect(songCoverSrc("https://p2.music.126.net/x.jpg?param=50y50")).toBe("https://p2.music.126.net/x.jpg?param=600y600");
  });

  it("leaves other hosts as they are", () => {
    expect(songCoverSrc("https://img.example.com/a.jpg")).toBe("https://img.example.com/a.jpg");
  });

  it("takes nothing that is not a web address", () => {
    expect(songCoverSrc(null)).toBeNull();
    expect(songCoverSrc(undefined)).toBeNull();
    expect(songCoverSrc("")).toBeNull();
    expect(songCoverSrc("http://p1.music.126.net/a.jpg")).toBeNull();
    expect(songCoverSrc("javascript:alert(1)")).toBeNull();
    expect(songCoverSrc("not a url")).toBeNull();
  });
});

describe("coverInFront", () => {
  it("shows the programme's cover until the programme has started, then the song's", () => {
    expect(coverInFront({ choice: null, songReady: true, started: false })).toBe("show");
    expect(coverInFront({ choice: null, songReady: true, started: true })).toBe("song");
  });

  it("keeps what the listener chose, from song to song", () => {
    expect(coverInFront({ choice: "show", songReady: true, started: true })).toBe("show");
    expect(coverInFront({ choice: "song", songReady: true, started: false })).toBe("song");
  });

  it("falls back to the programme's cover when the song has none", () => {
    expect(coverInFront({ choice: "song", songReady: false, started: true })).toBe("show");
    expect(coverInFront({ choice: null, songReady: false, started: true })).toBe("show");
  });
});

describe("the remembered choice", () => {
  it("is kept for the visit", () => {
    rememberCoverChoice("show");
    expect(rememberedCoverChoice()).toBe("show");
    rememberCoverChoice(null);
    expect(rememberedCoverChoice()).toBeNull();
  });
});
