"use client";

import { useEffect, useRef } from "react";

import { BottomSheet } from "../bottom-sheet";
import { CloseIcon } from "../icons";

export type NarrationPassage = { id: string; sentences: string[] };

/**
 * Everything the host has said in this programme so far. While the host is
 * talking, the spoken sentence is highlighted and kept in view; otherwise the
 * sheet opens at the latest passage. It can be opened at any time.
 */
export function NarrationSheet({
  open,
  onClose,
  subtitle,
  passages,
  activeId,
  activeIndex,
}: {
  open: boolean;
  onClose: () => void;
  subtitle: string;
  passages: NarrationPassage[];
  /** The passage being spoken right now, if any. */
  activeId: string | null;
  activeIndex: number;
}) {
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const activeAt = passages.findIndex((passage) => passage.id === activeId);

  useEffect(() => {
    if (!open) return;
    const root = bodyRef.current;
    if (!root) return;
    const target = root.querySelector<HTMLElement>("[data-current]")
      ?? (root.querySelector("li:last-of-type") ? [...root.querySelectorAll<HTMLElement>("li")].pop() : null);
    target?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [activeId, activeIndex, open, passages.length]);

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
      <div ref={bodyRef} className="ns-body">
        {passages.length ? (
          passages.map((passage, passageIndex) => (
            <ol key={passage.id} className="ns-list">
              {passage.sentences.map((sentence, i) => {
                const current = passageIndex === activeAt && i === activeIndex;
                const said = activeAt < 0 || passageIndex < activeAt || (passageIndex === activeAt && i < activeIndex);
                return (
                  <li
                    key={i}
                    className={current ? "is-current" : said ? "is-said" : "is-upcoming"}
                    aria-current={current || undefined}
                    data-current={current || undefined}
                  >
                    {sentence}
                  </li>
                );
              })}
            </ol>
          ))
        ) : (
          <p className="ns-empty">主持还没开口。开口之后，说过的话会留在这里。</p>
        )}
      </div>
    </BottomSheet>
  );
}
