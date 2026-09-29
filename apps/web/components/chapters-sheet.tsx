import type { LiveEpisode, Segment } from "../lib/types";
import { WaveIcon } from "./wave-icon";

type Chapter = {
  id: string;
  segments: Segment[];
};

function chaptersForEpisode(episode: LiveEpisode): Chapter[] {
  const result: Chapter[] = [];
  for (const segment of episode.segments) {
    let chapter = result.find((item) => item.id === segment.chapter_id);
    if (!chapter) {
      chapter = { id: segment.chapter_id, segments: [] };
      result.push(chapter);
    }
    chapter.segments.push(segment);
  }
  return result;
}

function chapterTitle(chapter: Chapter, index: number): string {
  const narration = chapter.segments.find(
    (segment) =>
      segment.kind === "NARRATION"
      && segment.state !== "PLANNED"
      && segment.state !== "SKIPPED"
      && Boolean(segment.narration_text),
  );
  if (narration && narration.title && narration.title !== "Track Intro") return narration.title;
  const fallback = ["开场", "夜色开始变暖", "从旋律走进城市", "另一面的节奏", "慢慢收回来"];
  return fallback[index] ?? "Chapter " + (index + 1);
}

export function ChaptersSheet({
  episode,
  open,
  currentSegmentId,
  onClose,
}: {
  episode: LiveEpisode;
  currentSegmentId?: string | null;
  open: boolean;
  onClose: () => void;
}) {
  if (!open) return null;
  const chapters = chaptersForEpisode(episode);
  const activeSegmentId = currentSegmentId ?? episode.current_segment_id;
  const currentIndex = chapters.findIndex((chapter) =>
    chapter.segments.some((segment) => segment.id === activeSegmentId),
  );

  return (
    <div className="sheet-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="chapters-sheet sheet-enter"
        role="dialog"
        aria-modal="true"
        aria-label="节目时间轴"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="sheet-grabber" />
        <div className="sheet-header">
          <div><p className="program-kicker">PROGRAM TIMELINE</p><h2>节目时间轴</h2></div>
          <button type="button" className="icon-button" aria-label="关闭" onClick={onClose}><WaveIcon name="close" /></button>
        </div>

        <div className="chapter-list">
          {chapters.map((chapter, index) => {
            const played = chapter.segments.every((segment) => segment.state === "PLAYED");
            const current = index === currentIndex;
            const music = chapter.segments.find((segment) => segment.kind === "MUSIC");
            return (
              <article className={current ? "chapter-row current" : "chapter-row"} key={chapter.id}>
                <div className="chapter-rail"><span>{played ? "✓" : current ? "▶" : ""}</span></div>
                <div className="chapter-number">{String(index + 1).padStart(2, "0")}</div>
                <div className="chapter-copy">
                  <strong>{chapterTitle(chapter, index)}</strong>
                  <small>{music ? [music.artist, music.title].filter(Boolean).join(" · ") : "旁白"}</small>
                  {current ? <em>正在播放</em> : null}
                </div>
              </article>
            );
          })}
        </div>
      </section>
    </div>
  );
}
