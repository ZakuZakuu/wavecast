import { GUIDES, type GuideDef, type GuideStep, type GuideTrigger } from "./registry";

// Which guides this device has seen, and which one is next. Kept on the device: a guest has no account.
const SEEN_KEY = "wavecast-guides-seen-v1";

export type SeenGuides = Record<string, number>;

export function readSeenGuides(): SeenGuides {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(SEEN_KEY) ?? "{}");
    if (!parsed || typeof parsed !== "object") return {};
    return Object.fromEntries(Object.entries(parsed as Record<string, unknown>).filter((entry): entry is [string, number] => typeof entry[1] === "number"));
  } catch {
    return {};
  }
}

/** Records a guide as seen at the version shown. */
export function markGuideSeen(def: GuideDef): void {
  const seen = readSeenGuides();
  seen[def.id] = def.version;
  try {
    window.localStorage.setItem(SEEN_KEY, JSON.stringify(seen));
  } catch {
    // Without storage the guide simply shows again next visit.
  }
}

/** 重看新手引导: every guide shows again. */
export function resetGuides(): void {
  try {
    window.localStorage.removeItem(SEEN_KEY);
  } catch {
    // Nothing stored, nothing to clear.
  }
}

/** The steps of a guide for a guest or a signed-in person. */
export function stepsFor(def: GuideDef, signedIn: boolean): GuideStep[] {
  const who = signedIn ? "member" : "guest";
  return def.steps.filter((step) => !step.audience || step.audience === who);
}

/**
 * The first unseen guide for this trigger. A guide counts as seen once its version has been shown;
 * one that `requires` another waits for it. With `signedIn` unknown (null) any guide may still apply.
 */
export function pickGuide(
  trigger: GuideTrigger,
  signedIn: boolean | null,
  seen: SeenGuides,
  guides: readonly GuideDef[] = GUIDES,
): GuideDef | null {
  return (
    guides.find((guide) => {
      if (guide.trigger !== trigger) return false;
      if ((seen[guide.id] ?? 0) >= guide.version) return false;
      if (guide.requires && !(seen[guide.requires] > 0)) return false;
      return signedIn === null || stepsFor(guide, signedIn).length > 0;
    }) ?? null
  );
}
