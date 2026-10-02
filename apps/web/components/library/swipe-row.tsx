"use client";

import { useRef, useState, type ReactNode } from "react";

const REVEAL = 84;
const THRESHOLD = 40;

/** List row that follows a left swipe and snaps open past 40px to reveal 删除. */
export function SwipeRow({
  children,
  onDelete,
  deleteLabel,
}: {
  children: ReactNode;
  onDelete?: () => void;
  deleteLabel: string;
}) {
  const [offset, setOffset] = useState(0);
  const [dragging, setDragging] = useState(false);
  const start = useRef<{ x: number; y: number; base: number; locked: "x" | "y" | null } | null>(null);
  const moved = useRef(false);

  if (!onDelete) return <li className="lib-row">{children}</li>;

  return (
    <li className="lib-row">
      <button
        type="button"
        className="lib-delete"
        onClick={onDelete}
        aria-label={deleteLabel}
        tabIndex={offset < 0 ? 0 : -1}
      >
        删除
      </button>
      <div
        className={dragging ? "lib-row-body is-dragging" : "lib-row-body"}
        style={{ transform: offset ? `translateX(${offset}px)` : undefined }}
        onPointerDown={(event) => {
          start.current = { x: event.clientX, y: event.clientY, base: offset, locked: null };
          moved.current = false;
        }}
        onPointerMove={(event) => {
          const s = start.current;
          if (!s) return;
          const dx = event.clientX - s.x;
          const dy = event.clientY - s.y;
          if (!s.locked && (Math.abs(dx) > 6 || Math.abs(dy) > 6)) {
            s.locked = Math.abs(dx) > Math.abs(dy) ? "x" : "y";
            if (s.locked === "x") {
              event.currentTarget.setPointerCapture(event.pointerId);
              setDragging(true);
            }
          }
          if (s.locked !== "x") return;
          moved.current = true;
          setOffset(Math.min(0, Math.max(-REVEAL - 24, s.base + dx)));
        }}
        onPointerUp={() => {
          const s = start.current;
          start.current = null;
          setDragging(false);
          if (!s || s.locked !== "x") return;
          setOffset((value) => (value < -THRESHOLD ? -REVEAL : 0));
        }}
        onPointerCancel={() => {
          start.current = null;
          setDragging(false);
          setOffset((value) => (value < -THRESHOLD ? -REVEAL : 0));
        }}
        onClickCapture={(event) => {
          // A swipe or a tap on an open row only closes it.
          if (moved.current) {
            // The click that ends a swipe.
            event.preventDefault();
            event.stopPropagation();
            moved.current = false;
            return;
          }
          if (offset < 0) {
            event.preventDefault();
            event.stopPropagation();
            setOffset(0);
          }
        }}
      >
        {children}
      </div>
    </li>
  );
}
