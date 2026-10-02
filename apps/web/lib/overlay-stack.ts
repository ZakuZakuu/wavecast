// One stack of open overlays (player, sheets, dialogs, 开播中):
// - Esc closes only the top-most one;
// - Back (Android back key / gesture, browser back) closes the top-most one
//   instead of leaving the page: each sheet/dialog pushes a same-URL history
//   entry while open, and closing it by other means removes that entry again.
// The player owns a real URL (/episode/…), so it registers without an entry.
import { useEffect, useRef } from "react";

const STATE_KEY = "wcOverlay";

type Entry = {
  close: () => void;
  /** History depth of this overlay's own entry; null when it owns none (yet). */
  level: number | null;
  /** Pending deferred pushState. */
  timer: ReturnType<typeof setTimeout> | null;
};

const stack: Entry[] = [];
let listening = false;
/** Pops we caused ourselves (history.back() while cleaning up an entry). */
let expectedPops = 0;

function historyLevel(state: unknown = typeof window === "undefined" ? null : window.history.state): number {
  const value = (state as Record<string, unknown> | null)?.[STATE_KEY];
  return typeof value === "number" ? value : 0;
}

function onKeyDown(event: KeyboardEvent): void {
  if (event.key !== "Escape" || event.defaultPrevented || event.isComposing) return;
  if (closeTopOverlay()) event.preventDefault();
}

function onPopState(event: PopStateEvent): void {
  if (expectedPops > 0) {
    expectedPops -= 1;
    return;
  }
  const level = historyLevel(event.state);
  // Close every overlay whose entry was just popped, top-most first.
  for (let index = stack.length - 1; index >= 0; index -= 1) {
    const entry = stack[index];
    if (entry.level !== null && entry.level > level) {
      entry.level = null;
      entry.close();
    }
  }
}

function ensureListeners(): void {
  if (listening || typeof window === "undefined") return;
  listening = true;
  window.addEventListener("keydown", onKeyDown);
  window.addEventListener("popstate", onPopState);
}

function pushEntry(entry: Entry): void {
  entry.timer = null;
  if (!stack.includes(entry)) return;
  const level = historyLevel() + 1;
  // Keep Next.js's own state (__NA, tree) so its popstate handling restores
  // the same page instead of reloading.
  const state = { ...(window.history.state ?? {}), [STATE_KEY]: level };
  window.history.pushState(state, "");
  entry.level = level;
}

/**
 * Registers an open overlay; returns its release function (call on close or
 * unmount). With `history`, a same-URL entry is pushed so Back closes it.
 */
export function registerOverlay(close: () => void, options: { history?: boolean } = {}): () => void {
  ensureListeners();
  const entry: Entry = { close, level: null, timer: null };
  stack.push(entry);
  if (options.history && typeof window !== "undefined") {
    // Deferred: a mount/unmount/remount (React StrictMode) never touches history.
    entry.timer = setTimeout(() => pushEntry(entry), 0);
  }
  return () => {
    const index = stack.indexOf(entry);
    if (index >= 0) stack.splice(index, 1);
    if (entry.timer !== null) {
      clearTimeout(entry.timer);
      entry.timer = null;
    }
    const level = entry.level;
    entry.level = null;
    // Closed by a button/scrim/Esc: drop its history entry if it is still
    // the current one (not when the page navigated on in the meantime).
    if (level !== null && historyLevel() === level) {
      expectedPops += 1;
      window.history.back();
    }
  };
}

/**
 * A navigation is replacing the current overlay entry (e.g. 开播中 handing
 * over to the player): open overlays stop owning history entries.
 */
export function detachOverlayHistory(): void {
  for (const entry of stack) {
    entry.level = null;
    if (entry.timer !== null) {
      clearTimeout(entry.timer);
      entry.timer = null;
    }
  }
}

/** True when the current history entry belongs to an overlay. */
export function onOverlayHistoryEntry(): boolean {
  return historyLevel() > 0;
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
export function useOverlay(open: boolean, close: () => void, options: { history?: boolean } = { history: true }): void {
  const closeRef = useRef(close);
  closeRef.current = close;
  const history = options.history !== false;
  useEffect(() => {
    if (!open) return;
    return registerOverlay(() => closeRef.current(), { history });
  }, [open, history]);
}
