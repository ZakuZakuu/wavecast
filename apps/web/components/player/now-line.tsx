"use client";

import { useLayoutEffect, useRef, useState } from "react";

import { formatClock } from "../../lib/now-playing";
import type { NowLineMode } from "../../lib/now-line";

export type NowLineNext = { primary: string; secondary: string };

/**
 * NowLine (播放状态条): a fixed-size frosted bar that is always mounted.
 * Exactly one of three panes is visible; switching cross-fades inside the box
 * so the progress bar and transport below never move.
 */
export function NowLine({
  mode,
  sentences,
  sentenceIndex,
  captions,
  next,
  preparedSeconds,
  onOpenNarration,
  onRetry,
}: {
  mode: NowLineMode;
  sentences: string[];
  sentenceIndex: number;
  captions: boolean;
  next: NowLineNext;
  preparedSeconds: number;
  onOpenNarration: () => void;
  onRetry?: () => void;
}) {
  const narrationHasText = sentences.length > 0;

  return (
    <div className="now-line" role="status">
      <div className={mode === "narration" ? "nl-pane is-active" : "nl-pane"} aria-hidden={mode !== "narration"}>
        <span className="nl-label">
          <span className="voice-bars" aria-hidden="true"><i /><i /><i /><i /><i /></span>
          主持在说
          {narrationHasText ? <span className="nl-more" aria-hidden="true">全文 &gt;</span> : null}
        </span>
        {captions && narrationHasText ? (
          <CaptionScroller sentences={sentences} index={sentenceIndex} />
        ) : (
          <NextLines next={next} />
        )}
      </div>

      <div className={mode === "preparing" ? "nl-pane is-active" : "nl-pane"} aria-hidden={mode !== "preparing"}>
        <span className="nl-label">
          <span className="nl-spinner" aria-hidden="true" />
          正在准备
          {onRetry ? (
            <button type="button" className="nl-retry" onClick={onRetry} tabIndex={mode === "preparing" ? 0 : -1}>重试</button>
          ) : null}
        </span>
        <span className="nl-body">
          <span className="nl-primary">正在准备接下来的内容，马上就好</span>
          <span className="nl-secondary tabular">已准备到 {formatClock(preparedSeconds)}</span>
        </span>
      </div>

      <div className={mode === "next" ? "nl-pane is-active" : "nl-pane"} aria-hidden={mode !== "next"}>
        <span className="nl-label">
          <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M7 4.5v15l12-7.5z" /></svg>
          接下来
        </span>
        <NextLines next={next} />
      </div>

      {mode === "narration" && narrationHasText ? (
        <button type="button" className="nl-open" aria-label="查看主持词全文" onClick={onOpenNarration} />
      ) : null}
    </div>
  );
}

function NextLines({ next }: { next: NowLineNext }) {
  return (
    <span className="nl-body">
      <span className="nl-primary nl-ellipsis">{next.primary}</span>
      <span className="nl-secondary nl-ellipsis">{next.secondary}</span>
    </span>
  );
}

/**
 * Rolling captions: the whole narration sits in a 45px window and is shifted
 * so the current sentence's first line aligns with the top. No aria-live.
 */
function CaptionScroller({ sentences, index }: { sentences: string[]; index: number }) {
  const listRef = useRef<HTMLDivElement | null>(null);
  const [offset, setOffset] = useState(0);

  useLayoutEffect(() => {
    const list = listRef.current;
    const node = list?.children[Math.max(0, index)] as HTMLElement | undefined;
    setOffset(node ? node.offsetTop : 0);
  }, [index, sentences]);

  return (
    <span className="nl-captions" aria-hidden="true">
      <div ref={listRef} className="nl-caption-list" style={{ transform: `translateY(${-offset}px)` }}>
        {sentences.map((sentence, i) => (
          <span key={i} className={i === index ? "nl-sentence is-current" : "nl-sentence"}>{sentence}</span>
        ))}
      </div>
    </span>
  );
}
