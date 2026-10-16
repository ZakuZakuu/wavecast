import { describe, expect, it } from "vitest";

import { publishedNarration } from "../lib/now-playing";
import type { MixPlan } from "../lib/mix-timeline";

const clip = (segmentId: string, start: number, lane: "VOICE" | "MUSIC" = "VOICE") => ({
  id: `${segmentId}:${lane}`,
  segmentId,
  sourceUrl: "x",
  lane,
  timelineStartSeconds: start,
  sourceOffsetSeconds: 0,
  playableDurationSeconds: 10,
  gain: 1,
  fadeInSeconds: 0,
  fadeOutSeconds: 0,
  gainAutomation: [],
});
const plan = (clips: ReturnType<typeof clip>[]): MixPlan => ({
  schemaVersion: 1, episodeId: "e", durationSeconds: 1000, clips, segmentStarts: {},
});
const narration = (id: string, state: string, text: string | null) =>
  ({ id, kind: "NARRATION", state, narration_text: text }) as never;
const music = (id: string) => ({ id, kind: "MUSIC", state: "PLAYED" }) as never;

describe("the host's words that are published", () => {
  const episode = {
    segments: [
      narration("opening", "PLAYED", "欢迎来到这一期。"),
      music("m1"),
      narration("bridge", "AUDIO_READY", "下一首是《因为你》。"),
      narration("skipped", "SKIPPED", "这句被跳过了。"),
      narration("draft", "SCRIPT_READY", "这句还只是草稿。"),
      narration("ahead", "AUDIO_READY", "这句还没有发布。"),
    ],
  };
  const clips = plan([
    clip("bridge", 200), clip("opening", 4), clip("m1", 15, "MUSIC"),
    clip("skipped", 300), clip("draft", 310), clip("ahead", 900),
  ]);

  it("lists published, ready narration in programme order, including the opening", () => {
    expect(publishedNarration(episode, clips, 500).map((item) => item.id)).toEqual(["opening", "bridge"]);
  });

  it("is the same whoever was listening: it only depends on the programme", () => {
    expect(publishedNarration(episode, clips, 500)).toEqual(publishedNarration({ ...episode }, clips, 500));
  });

  it("leaves out skipped narration, drafts and what lies beyond the published audio", () => {
    const ids = publishedNarration(episode, clips, 500).map((item) => item.id);
    expect(ids).not.toContain("skipped");
    expect(ids).not.toContain("draft");
    expect(ids).not.toContain("ahead");
  });

  it("grows as more of the programme is published", () => {
    expect(publishedNarration(episode, clips, 950).map((item) => item.id)).toEqual(["opening", "bridge", "ahead"]);
  });

  it("is empty until the mix plan is known", () => {
    expect(publishedNarration(episode, null, 500)).toEqual([]);
  });
});
