// Soft keyboard on phones (Android Chrome resizes only the visual viewport):
// while it is open, the document is pinned to the visible area so the
// focused field and the CTA stay above the keyboard and nothing can scroll
// into blank space beneath.
import { useEffect } from "react";

/** Smaller differences are browser chrome (URL bar), not a keyboard. */
export const KEYBOARD_MIN_PX = 120;

export type ViewportSample = { innerHeight: number; height: number; offsetTop: number };

/** Height hidden below the visible viewport, or 0 when no keyboard is open. */
export function keyboardInset(sample: ViewportSample): number {
  const hidden = Math.round(sample.innerHeight - sample.height - Math.max(0, sample.offsetTop));
  return hidden >= KEYBOARD_MIN_PX ? hidden : 0;
}

/** Visible height to pin the app to while the keyboard is open (null when closed). */
export function pinnedHeight(sample: ViewportSample): number | null {
  return keyboardInset(sample) > 0 ? Math.round(sample.height) : null;
}

const OPEN_CLASS = "kb-open";

/** Active while `enabled`: toggles html.kb-open and --kb-height from visualViewport. */
export function useSoftKeyboard(enabled = true): void {
  useEffect(() => {
    const viewport = typeof window === "undefined" ? undefined : window.visualViewport;
    if (!enabled || !viewport) return;
    const root = document.documentElement;
    let frame = 0;
    const apply = () => {
      frame = 0;
      const height = pinnedHeight({ innerHeight: window.innerHeight, height: viewport.height, offsetTop: viewport.offsetTop });
      if (height === null) {
        root.classList.remove(OPEN_CLASS);
        root.style.removeProperty("--kb-height");
        return;
      }
      root.style.setProperty("--kb-height", `${height}px`);
      root.classList.add(OPEN_CLASS);
      // Undo the browser's scroll-into-view: the app already fits.
      if (window.scrollY !== 0 || viewport.offsetTop !== 0) window.scrollTo(0, 0);
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(apply);
    };
    viewport.addEventListener("resize", schedule);
    viewport.addEventListener("scroll", schedule);
    apply();
    return () => {
      viewport.removeEventListener("resize", schedule);
      viewport.removeEventListener("scroll", schedule);
      if (frame) cancelAnimationFrame(frame);
      root.classList.remove(OPEN_CLASS);
      root.style.removeProperty("--kb-height");
    };
  }, [enabled]);
}
