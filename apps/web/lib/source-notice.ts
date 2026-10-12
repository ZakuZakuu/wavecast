import type { SourceNotice } from "./types";

/**
 * One quiet line for the listener when a requested artist has nothing playable.
 * The server sends facts only (kind + artist names); the wording lives here so a
 * model can never invent a reason.
 */
export function sourceNoticeText(notice: SourceNotice | null | undefined): string | null {
  if (!notice || notice.kind !== "UNPLAYABLE_ARTISTS") return null;
  const artists = notice.artists.map((name) => name.trim()).filter(Boolean).slice(0, 3);
  if (artists.length === 0) return null;
  return `暂时没有找到 ${artists.join("、")} 可以播放的音源，已为你搭配相近的曲目。`;
}
