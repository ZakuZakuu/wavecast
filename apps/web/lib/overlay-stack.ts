// One stack of open overlays (player, sheets, dialogs, 开播中) so Esc closes
// only the top-most one.
import { useEffect, useRef } from "react";

type Entry = { id: number; close: () => void };

const stack: Entry[] = [];
let nextId = 1;
let keyListening = false;

function onKeyDown(event: KeyboardEvent): void {
  if (event.key !== "Escape" || event.defaultPrevented || event.isComposing) return;
  if (closeTopOverlay()) event.preventDefault();
}

function ensureKeyListener(): void {
  if (keyListening || typeof window === "undefined") return;
  keyListening = true;
  window.addEventListener("keydown", onKeyDown);
}

/** Registers an open overlay; returns its release function (call on close/unmount). */
export function registerOverlay(close: () => void): () => void {
  ensureKeyListener();
  const entry: Entry = { id: nextId++, close };
  stack.push(entry);
  return () => {
    const index = stack.indexOf(entry);
    if (index >= 0) stack.splice(index, 1);
  };
}

/** Closes the top-most overlay. Returns false when none is open. */
export function closeTopOverlay(): boolean {
  const top = stack[stack.length - 1];
  if (!top) return false;
  top.close();
  return true;
}

export function openOverlayCount(): number {
  return stack.length;
}

/** Keeps an overlay registered while `open`; `close` may change between renders. */
export function useOverlay(open: boolean, close: () => void): void {
  const closeRef = useRef(close);
  closeRef.current = close;
  useEffect(() => {
    if (!open) return;
    return registerOverlay(() => closeRef.current());
  }, [open]);
}
