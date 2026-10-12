import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { NarrationSheet, type NarrationPassage } from "../components/player/narration-sheet";

const passages: NarrationPassage[] = [
  { id: "n1", sentences: ["第一段第一句。", "第一段第二句。"] },
  { id: "n2", sentences: ["第二段第一句。", "第二段第二句。"] },
];

describe("NarrationSheet", () => {
  let root: Root;
  let container: HTMLDivElement;

  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    Element.prototype.scrollIntoView = () => undefined;
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    document.body.innerHTML = "";
  });

  const render = (props: { passages: NarrationPassage[]; activeId: string | null; activeIndex: number }) =>
    act(async () => {
      root.render(createElement(NarrationSheet, { open: true, onClose: () => undefined, subtitle: "节目", ...props }));
    });

  const state = () =>
    [...document.querySelectorAll(".ns-list li")].map((li) => `${li.textContent}:${li.className}`);

  it("opens with an explanation, not an empty list, before the host has said anything", async () => {
    await render({ passages: [], activeId: null, activeIndex: 0 });
    expect(document.querySelector(".ns-empty")?.textContent).toContain("主持还没开口");
    expect(document.querySelectorAll(".ns-list li")).toHaveLength(0);
  });

  it("keeps everything already said and marks it said when the host is not talking", async () => {
    await render({ passages, activeId: null, activeIndex: 0 });
    expect(state()).toEqual([
      "第一段第一句。:is-said",
      "第一段第二句。:is-said",
      "第二段第一句。:is-said",
      "第二段第二句。:is-said",
    ]);
    expect(document.querySelector("[data-current]")).toBeNull();
  });

  it("highlights the spoken sentence of the passage being spoken, earlier passages are said", async () => {
    await render({ passages, activeId: "n2", activeIndex: 1 });
    expect(state()).toEqual([
      "第一段第一句。:is-said",
      "第一段第二句。:is-said",
      "第二段第一句。:is-said",
      "第二段第二句。:is-current",
    ]);
    expect(document.querySelector("[aria-current]")?.textContent).toBe("第二段第二句。");
  });

  it("marks later sentences of the active passage as upcoming", async () => {
    await render({ passages, activeId: "n1", activeIndex: 0 });
    expect(state()[0]).toContain("is-current");
    expect(state()[1]).toContain("is-upcoming");
    expect(state()[2]).toContain("is-upcoming");
  });
});
