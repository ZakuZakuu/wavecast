"use client";

import { useEffect, useRef } from "react";

import { BottomSheet } from "../bottom-sheet";
import { CloseIcon } from "../icons";

/** Full host script with the spoken sentence highlighted and kept in view. */
export function NarrationSheet({
  open,
  onClose,
  subtitle,
  sentences,
  index,
}: {
  open: boolean;
  onClose: () => void;
  subtitle: string;
  sentences: string[];
  index: number;
}) {
  const listRef = useRef<HTMLOListElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const node = listRef.current?.children[index] as HTMLElement | undefined;
    node?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [index, open]);

  return (
    <BottomSheet open={open} onClose={onClose} label="主持词" tone="dark" height="min(560px, calc(100dvh - 60px))" className="narration-sheet">
      <header className="route-head">
        <div>
          <h2>主持词</h2>
          <p>{subtitle}</p>
        </div>
        <button type="button" className="route-close" aria-label="关闭" onClick={onClose}>
          <CloseIcon size={16} strokeWidth={2.4} />
        </button>
      </header>
      <ol ref={listRef} className="ns-list">
        {sentences.map((sentence, i) => (
          <li
            key={i}
            className={i < index ? "is-said" : i === index ? "is-current" : "is-upcoming"}
            aria-current={i === index || undefined}
          >
            {sentence}
          </li>
        ))}
      </ol>
      <p className="ns-foot">字幕跟着主持的进度走，正在说的那句会高亮。</p>
    </BottomSheet>
  );
}
