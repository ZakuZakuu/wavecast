import { describe, expect, it } from "vitest";

import {
  currentSentenceIndex,
  NARRATION_CHARS_PER_SECOND,
  nowLineMode,
  sentenceStarts,
  splitSentences,
} from "../lib/now-line";

describe("splitSentences", () => {
  it("splits on Chinese and Latin terminators and keeps punctuation", () => {
    expect(splitSentences("注意副歌前那段和声。下一首也是这么开头的！你听出来了吗？好；走吧…"))
      .toEqual(["注意副歌前那段和声。", "下一首也是这么开头的！", "你听出来了吗？", "好；", "走吧…"]);
    expect(splitSentences("This is City Pop. Ready? Go!")).toEqual(["This is City Pop.", "Ready?", "Go!"]);
  });

  it("keeps a trailing sentence without punctuation and closing quotes with their sentence", () => {
    expect(splitSentences("他说：“就这样。”然后停下")).toEqual(["他说：“就这样。”", "然后停下"]);
  });

  it("splits sentences over 40 characters at commas", () => {
    const long = "这首歌录于一九八五年的东京，那时候城市流行正在最好的年份，"
      + "录音室里有很多后来很有名的乐手，他们一起把这种声音做了出来。";
    const parts = splitSentences(long);
    expect(parts.length).toBeGreaterThan(1);
    expect(parts.join("")).toBe(long);
    expect(parts.every((part) => [...part].length <= 40)).toBe(true);
  });

  it("returns nothing for empty text", () => {
    expect(splitSentences("  ")).toEqual([]);
  });
});

describe("current sentence timing", () => {
  const sentences = ["一二三四五。", "一二三四五六七八九十。", "一二三四五。"]; // 6, 11, 6 chars

  it("shares a known duration by character count", () => {
    const starts = sentenceStarts(sentences, 23);
    expect(starts).toEqual([0, 6, 17]);
    expect(currentSentenceIndex(sentences, 0, 23)).toBe(0);
    expect(currentSentenceIndex(sentences, 5.9, 23)).toBe(0);
    expect(currentSentenceIndex(sentences, 6, 23)).toBe(1);
    expect(currentSentenceIndex(sentences, 22, 23)).toBe(2);
    expect(currentSentenceIndex(sentences, 99, 23)).toBe(2);
  });

  it("falls back to the chars-per-second constant", () => {
    const starts = sentenceStarts(sentences, null);
    expect(starts[1]).toBeCloseTo(6 / NARRATION_CHARS_PER_SECOND);
    expect(currentSentenceIndex(sentences, 6 / NARRATION_CHARS_PER_SECOND + 0.01, null)).toBe(1);
  });

  it("re-derives from position after a seek backwards", () => {
    expect(currentSentenceIndex(sentences, 20, 23)).toBe(2);
    expect(currentSentenceIndex(sentences, 3, 23)).toBe(0);
    expect(currentSentenceIndex(sentences, -15, 23)).toBe(0);
    expect(currentSentenceIndex([], 3, 23)).toBe(-1);
  });
});

describe("nowLineMode", () => {
  it("prioritises narration, then preparing, then next", () => {
    expect(nowLineMode({ narrating: true, preparing: true })).toBe("narration");
    expect(nowLineMode({ narrating: false, preparing: true })).toBe("preparing");
    expect(nowLineMode({ narrating: false, preparing: false })).toBe("next");
  });
});
