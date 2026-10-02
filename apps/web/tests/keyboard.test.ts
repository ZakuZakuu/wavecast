import { afterEach, describe, expect, it } from "vitest";

import { isTypingTarget, spaceTogglesPlayback } from "../lib/keyboard";

function space(target: EventTarget | null, extra: Partial<KeyboardEvent> = {}) {
  return {
    key: " ", code: "Space", target, repeat: false, defaultPrevented: false,
    altKey: false, ctrlKey: false, metaKey: false, ...extra,
  } as KeyboardEvent;
}

afterEach(() => {
  document.body.innerHTML = "";
});

describe("keyboard shortcuts", () => {
  it("never claims Space inside text fields", () => {
    document.body.innerHTML = `<input id="t" type="text"><textarea id="a"></textarea><div id="e" contenteditable="true"></div><input id="c" type="checkbox">`;
    expect(isTypingTarget(document.getElementById("t"))).toBe(true);
    expect(isTypingTarget(document.getElementById("a"))).toBe(true);
    expect(spaceTogglesPlayback(space(document.getElementById("t")))).toBe(false);
    expect(spaceTogglesPlayback(space(document.getElementById("a")))).toBe(false);
    expect(isTypingTarget(document.getElementById("c"))).toBe(false);
  });

  it("toggles from the page body", () => {
    expect(spaceTogglesPlayback(space(document.body))).toBe(true);
  });

  it("ignores other keys, repeats and modified presses", () => {
    expect(spaceTogglesPlayback(space(document.body, { key: "Enter", code: "Enter" }))).toBe(false);
    expect(spaceTogglesPlayback(space(document.body, { repeat: true }))).toBe(false);
    expect(spaceTogglesPlayback(space(document.body, { metaKey: true }))).toBe(false);
    expect(spaceTogglesPlayback(space(document.body, { defaultPrevented: true }))).toBe(false);
  });
});
