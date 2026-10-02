// NowLine (播放状态条) pure logic: state priority, sentence split, caption timing.

/** Fallback narration speed when the clip timing is unknown (chars / second). */
export const NARRATION_CHARS_PER_SECOND = 4.5;
const MAX_SENTENCE_CHARS = 40;

export type NowLineMode = "narration" | "preparing" | "next";

/** Priority: host speaking > preparing > up next. */
export function nowLineMode(input: { narrating: boolean; preparing: boolean }): NowLineMode {
  if (input.narrating) return "narration";
  if (input.preparing) return "preparing";
  return "next";
}

function charCount(text: string): number {
  return [...text.replace(/\s+/g, "")].length;
}

/**
 * Splits narration into sentences on 。！？；… and .!? (punctuation kept).
 * A sentence longer than 40 characters is split once more at commas.
 */
export function splitSentences(text: string): string[] {
  const normalized = text.replace(/\s+/g, " ").trim();
  if (!normalized) return [];
  const parts = normalized.match(/[^。！？；…!?.]+(?:[。！？；…!?.]+|$)["”’」』)）]*/g) ?? [normalized];
  const sentences: string[] = [];
  for (const raw of parts) {
    const sentence = raw.trim();
    if (!sentence) continue;
    if (charCount(sentence) <= MAX_SENTENCE_CHARS) {
      sentences.push(sentence);
      continue;
    }
    const pieces = sentence.match(/[^，,、]+(?:[，,、]+|$)/g) ?? [sentence];
    // Re-join comma pieces into chunks that stay within the limit.
    let chunk = "";
    for (const piece of pieces) {
      if (chunk && charCount(chunk + piece) > MAX_SENTENCE_CHARS) {
        sentences.push(chunk.trim());
        chunk = "";
      }
      chunk += piece;
    }
    if (chunk.trim()) sentences.push(chunk.trim());
  }
  return sentences;
}

/**
 * Start offsets (seconds from narration start) of each sentence. With a known
 * clip duration, time is shared in proportion to character count; otherwise
 * NARRATION_CHARS_PER_SECOND is assumed.
 */
export function sentenceStarts(sentences: string[], durationSeconds: number | null): number[] {
  const counts = sentences.map((sentence) => Math.max(1, charCount(sentence)));
  const total = counts.reduce((sum, value) => sum + value, 0);
  const perChar = durationSeconds && durationSeconds > 0 && total > 0
    ? durationSeconds / total
    : 1 / NARRATION_CHARS_PER_SECOND;
  const starts: number[] = [];
  let running = 0;
  for (const count of counts) {
    starts.push(running);
    running += count * perChar;
  }
  return starts;
}

/** Index of the sentence being spoken `elapsedSeconds` into the narration. */
export function currentSentenceIndex(
  sentences: string[],
  elapsedSeconds: number,
  durationSeconds: number | null,
): number {
  if (!sentences.length) return -1;
  const starts = sentenceStarts(sentences, durationSeconds);
  const elapsed = Math.max(0, elapsedSeconds);
  let index = 0;
  for (let i = 0; i < starts.length; i += 1) {
    if (starts[i] <= elapsed) index = i;
    else break;
  }
  return index;
}
