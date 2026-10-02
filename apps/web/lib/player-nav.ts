// Opening/closing the player overlay without unmounting the page beneath it.
// The URL still changes (shareable, back button works): a history.pushState
// that Next.js syncs into usePathname without rendering a new page.

import { detachOverlayHistory, onOverlayHistoryEntry } from "./overlay-stack";

export type PlayerOpenSource = "mini" | "fade" | "slide";

export type PlayerTargetFromPath = { seedId?: string; episodeId?: string };

let pendingSource: { source: PlayerOpenSource; rect: DOMRect | null } | null = null;
let openedInApp = false;
let lastMiniCoverRect: DOMRect | null = null;

export function playerTargetFromPath(pathname: string | null): PlayerTargetFromPath | null {
  if (!pathname) return null;
  const materialized = pathname.match(/^\/episode\/materialized\/([^/]+)\/?$/);
  if (materialized) return { episodeId: decodeURIComponent(materialized[1]) };
  const seed = pathname.match(/^\/episode\/([^/]+)\/?$/);
  if (seed && seed[1] !== "materialized") return { seedId: decodeURIComponent(seed[1]) };
  return null;
}

function miniCoverRect(): DOMRect | null {
  if (typeof document === "undefined") return null;
  const element = document.querySelector(".mini-player:not([hidden]) .mini-cover");
  return element ? element.getBoundingClientRect() : null;
}

/** Remember where the mini cover sits so a collapse can shrink back into it. */
export function rememberMiniCoverRect(): void {
  const rect = miniCoverRect();
  if (rect && rect.width > 0) lastMiniCoverRect = rect;
}

export function miniCoverTargetRect(): DOMRect | null {
  return miniCoverRect() ?? lastMiniCoverRect;
}

export function openPlayer(href: string, source: PlayerOpenSource = "slide"): void {
  rememberMiniCoverRect();
  const rect = source === "mini" ? lastMiniCoverRect : null;
  pendingSource = { source, rect };
  openedInApp = true;
  if (onOverlayHistoryEntry()) {
    // An overlay (开播中) owns the current entry and hands over to the
    // player: replace it, so Back from the player returns to the page.
    detachOverlayHistory();
    window.history.replaceState(null, "", href);
    return;
  }
  window.history.pushState(null, "", href);
}

export function takeOpenSource(): { source: PlayerOpenSource; rect: DOMRect | null } {
  const value = pendingSource ?? { source: "slide" as const, rect: null };
  pendingSource = null;
  return value;
}

/** True when the current player entry was pushed by openPlayer (so Back returns). */
export function playerOpenedInApp(): boolean {
  return openedInApp;
}

export function resetPlayerOpened(): void {
  openedInApp = false;
}
