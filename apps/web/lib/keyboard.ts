// Global keyboard shortcuts (desktop): which key events the app may claim.

const TEXT_INPUT_TYPES = new Set([
  "text", "search", "email", "url", "tel", "password", "number", "date", "time", "datetime-local", "month", "week",
]);

/** True when the target accepts typing, so Space must reach it untouched. */
export function isTypingTarget(target: EventTarget | null): boolean {
  if (!target || typeof (target as Element).closest !== "function") return false;
  const element = target as HTMLElement;
  if (element.isContentEditable) return true;
  if (element.tagName === "TEXTAREA" || element.tagName === "SELECT") return true;
  if (element.tagName === "INPUT") return TEXT_INPUT_TYPES.has((element as HTMLInputElement).type || "text");
  return false;
}

/**
 * Space activates a keyboard-focused control (button, link, slider…), so it
 * only toggles playback when focus is not on one. A control focused by a
 * mouse click (no :focus-visible) does not swallow it.
 */
export function spaceTogglesPlayback(event: Pick<KeyboardEvent, "key" | "code" | "target" | "repeat" | "defaultPrevented" | "altKey" | "ctrlKey" | "metaKey">): boolean {
  if (event.key !== " " && event.code !== "Space") return false;
  if (event.repeat || event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return false;
  if (isTypingTarget(event.target)) return false;
  const element = event.target as HTMLElement | null;
  if (element && typeof element.closest === "function") {
    const control = element.closest("button, a[href], summary, [role='button'], [role='slider'], [role='switch'], [role='radio'], [role='tab'], input");
    if (control && safeMatches(control, ":focus-visible")) return false;
  }
  return true;
}

function safeMatches(element: Element, selector: string): boolean {
  try {
    return element.matches(selector);
  } catch {
    return true;
  }
}
