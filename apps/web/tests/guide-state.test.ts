import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { beforeEach, describe, expect, it } from "vitest";

import { GUIDES, type GuideDef } from "../lib/guide/registry";
import { markGuideSeen, pickGuide, readSeenGuides, resetGuides, stepsFor } from "../lib/guide/state";

const def = (id: string, extra: Partial<GuideDef> = {}): GuideDef => ({ id, version: 1, trigger: "home", steps: [{ text: "步骤" }], ...extra });

beforeEach(() => window.localStorage.clear());

describe("guide state", () => {
  it("remembers what was shown, at which version", () => {
    expect(readSeenGuides()).toEqual({});
    markGuideSeen(def("a", { version: 2 }));
    markGuideSeen(def("b"));
    expect(readSeenGuides()).toEqual({ a: 2, b: 1 });
    resetGuides();
    expect(readSeenGuides()).toEqual({});
  });

  it("ignores damaged storage", () => {
    window.localStorage.setItem("wavecast-guides-seen-v1", "{not json");
    expect(readSeenGuides()).toEqual({});
    window.localStorage.setItem("wavecast-guides-seen-v1", JSON.stringify({ a: 1, b: "x", c: null }));
    expect(readSeenGuides()).toEqual({ a: 1 });
  });

  it("picks the first unseen guide of the trigger", () => {
    const guides = [def("one"), def("two"), def("tune", { trigger: "tune" })];
    expect(pickGuide("home", false, {}, guides)?.id).toBe("one");
    expect(pickGuide("home", false, { one: 1 }, guides)?.id).toBe("two");
    expect(pickGuide("home", false, { one: 1, two: 1 }, guides)).toBeNull();
    expect(pickGuide("tune", false, { one: 1 }, guides)?.id).toBe("tune");
  });

  it("shows a guide again when its version goes up, and only that one", () => {
    const guides = [def("one", { version: 2 }), def("two")];
    expect(pickGuide("home", true, { one: 1, two: 1 }, guides)?.id).toBe("one");
    expect(pickGuide("home", true, { one: 2, two: 1 }, guides)).toBeNull();
  });

  it("a new guide is the only thing an existing user is shown", () => {
    const old = [def("one"), def("two")];
    const seen = { one: 1, two: 1 };
    expect(pickGuide("home", true, seen, old)).toBeNull();
    expect(pickGuide("home", true, seen, [...old, def("new")])?.id).toBe("new");
  });

  it("waits for the guide it requires", () => {
    const guides = [def("intro"), def("after", { requires: "intro" })];
    expect(pickGuide("home", true, { intro: 1 }, guides)?.id).toBe("after");
    expect(pickGuide("home", true, {}, [guides[1]])).toBeNull();
  });

  it("filters steps by who is looking, and skips a guide with nothing for them", () => {
    const guide = def("x", { steps: [{ text: "all" }, { text: "guest", audience: "guest" }, { text: "member", audience: "member" }] });
    expect(stepsFor(guide, false).map((step) => step.text)).toEqual(["all", "guest"]);
    expect(stepsFor(guide, true).map((step) => step.text)).toEqual(["all", "member"]);
    const memberOnly = def("m", { steps: [{ text: "m", audience: "member" }] });
    expect(pickGuide("home", false, {}, [memberOnly])).toBeNull();
    expect(pickGuide("home", true, {}, [memberOnly])?.id).toBe("m");
    expect(pickGuide("home", null, {}, [memberOnly])?.id).toBe("m");
  });
});

describe("guide registry", () => {
  it("has unique ids, known requirements and wording on every step", () => {
    const ids = GUIDES.map((guide) => guide.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const guide of GUIDES) {
      expect(guide.version).toBeGreaterThanOrEqual(1);
      if (guide.requires) expect(ids).toContain(guide.requires);
      for (const step of guide.steps) expect(step.text.trim().length).toBeGreaterThan(4);
      expect(stepsFor(guide, true).length + stepsFor(guide, false).length).toBeGreaterThan(0);
    }
  });

  it("only sends people on from the last step they see", () => {
    for (const guide of GUIDES) {
      for (const signedIn of [false, true]) {
        const steps = stepsFor(guide, signedIn);
        steps.forEach((step, index) => {
          if (step.href) expect(index).toBe(steps.length - 1);
        });
      }
    }
  });

  it("lights up elements that exist in the app (a renamed marker fails here, not for the listener)", () => {
    const sources: string[] = [];
    const walk = (dir: string) => {
      for (const name of readdirSync(dir)) {
        const path = join(dir, name);
        if (statSync(path).isDirectory()) walk(path);
        else if (/\.tsx$/.test(name)) sources.push(readFileSync(path, "utf8"));
      }
    };
    walk(join(__dirname, "..", "components"));
    const text = sources.join("\n");
    const marked = (target: string) => text.includes(`data-guide="${target}"`) || text.includes(`guide="${target}"`) || text.includes(`guide: "${target}"`);
    for (const guide of GUIDES) {
      for (const step of guide.steps) if (step.target) expect(marked(step.target), `${guide.id}: ${step.target}`).toBe(true);
    }
  });
});
