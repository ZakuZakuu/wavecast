import { describe, expect, it } from "vitest";

import { keyboardInset, pinnedHeight } from "../lib/soft-keyboard";

describe("soft keyboard", () => {
  it("ignores browser chrome changes", () => {
    expect(keyboardInset({ innerHeight: 800, height: 744, offsetTop: 0 })).toBe(0);
    expect(pinnedHeight({ innerHeight: 800, height: 744, offsetTop: 0 })).toBeNull();
  });

  it("detects an open keyboard and pins the app to the visible height", () => {
    expect(keyboardInset({ innerHeight: 800, height: 470, offsetTop: 0 })).toBe(330);
    expect(pinnedHeight({ innerHeight: 800, height: 470.4, offsetTop: 0 })).toBe(470);
  });

  it("accounts for a panned visual viewport", () => {
    expect(keyboardInset({ innerHeight: 800, height: 470, offsetTop: 120 })).toBe(210);
    expect(pinnedHeight({ innerHeight: 800, height: 470, offsetTop: 120 })).toBe(470);
  });
});
