"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { authClient } from "../../lib/auth-client";
import { type GuideDef, type GuideStep, type GuideTrigger } from "../../lib/guide/registry";
import { markGuideSeen, pickGuide, readSeenGuides, stepsFor } from "../../lib/guide/state";
import { placeBubble, SPOT_PAD, type Box } from "../../lib/guide/layout";
import { claimVisitPrompt } from "../../lib/login-nudge";
import { openOverlayCount, useOverlay } from "../../lib/overlay-stack";
import { Portal } from "../portal";

const RETRY_MS = 400;
/** How long a page waits for its guide to be able to start (a covering sheet, a card still loading). */
const RETRY_LIMIT = 75;
const SETTLE_MS = 600;

const find = (target: string) => document.querySelector<HTMLElement>(`[data-guide="${target}"]`);
const present = (step: GuideStep) => !step.target || Boolean(find(step.target));

/** The next step at or after `from` whose element is on screen. */
function nextShown(steps: GuideStep[], from: number): number {
  for (let index = from; index < steps.length; index += 1) if (present(steps[index])) return index;
  return -1;
}

type Run = { def: GuideDef; steps: GuideStep[]; index: number };

/**
 * First-use guide for one page (lib/guide). Waits until nothing else is open and the page has what it lights up,
 * then shows the page's unseen guide a step at a time. `ready`: the page has settled (taste sheet done).
 */
export function Guide({ trigger, ready = true }: { trigger: GuideTrigger; ready?: boolean }) {
  const router = useRouter();
  const { data, isPending } = authClient.useSession();
  return (
    <GuideRunner
      trigger={trigger}
      signedIn={isPending ? null : Boolean(data?.user)}
      ready={ready}
      onNavigate={(href) => router.push(href)}
    />
  );
}

export function GuideRunner({
  trigger,
  signedIn,
  ready,
  onNavigate,
}: {
  trigger: GuideTrigger;
  /** null while the session is still loading. */
  signedIn: boolean | null;
  ready: boolean;
  onNavigate: (href: string) => void;
}) {
  const [run, setRun] = useState<Run | null>(null);
  // One guide per page view: the next unseen one waits for the next visit.
  const finished = useRef(false);
  const holdsSlot = useRef<boolean | null>(null);

  // Held from the first moment, so the install prompt (which waits a little) does not take the visit's slot.
  useEffect(() => {
    if (holdsSlot.current === null && pickGuide(trigger, null, readSeenGuides())) holdsSlot.current = claimVisitPrompt("guide");
  }, [trigger]);

  useEffect(() => {
    if (run || finished.current || !ready || signedIn === null || holdsSlot.current !== true) return;
    const def = pickGuide(trigger, signedIn, readSeenGuides());
    if (!def) return;
    const steps = stepsFor(def, signedIn);
    let attempts = 0;
    let timer: number;
    const attempt = () => {
      attempts += 1;
      const first = openOverlayCount() > 0 ? -1 : nextShown(steps, 0);
      if (first >= 0) setRun({ def, steps, index: first });
      else if (attempts < RETRY_LIMIT) timer = window.setTimeout(attempt, RETRY_MS);
    };
    timer = window.setTimeout(attempt, SETTLE_MS);
    return () => window.clearTimeout(timer);
  }, [run, ready, signedIn, trigger]);

  const end = useCallback((href?: string) => {
    setRun((current) => {
      if (current) markGuideSeen(current.def);
      return null;
    });
    finished.current = true;
    if (href) onNavigate(href);
  }, [onNavigate]);

  useOverlay(Boolean(run), () => end(), { history: false });

  if (!run) return null;
  const step = run.steps[run.index];
  const next = nextShown(run.steps, run.index + 1);
  const last = next < 0;
  return (
    <Portal>
      <GuideCard
        step={step}
        position={run.index + 1}
        total={run.steps.length}
        last={last}
        onNext={() => (last ? end(step.href) : setRun({ ...run, index: next }))}
        onSkip={() => end()}
      />
    </Portal>
  );
}

/** The lit element's box, kept up to date while the page settles, scrolls or resizes. */
function useTargetBox(target: string | undefined): { box: Box | null; radius: number } {
  const [state, setState] = useState<{ box: Box | null; radius: number }>({ box: null, radius: 12 });
  useLayoutEffect(() => {
    const element = target ? find(target) : null;
    if (!element) {
      setState({ box: null, radius: 12 });
      return;
    }
    element.scrollIntoView({ block: "center", inline: "nearest" });
    const measure = () => {
      const rect = element.getBoundingClientRect();
      const radius = parseFloat(getComputedStyle(element).borderTopLeftRadius) || 12;
      setState((previous) => {
        const same = previous.box && previous.box.left === rect.left && previous.box.top === rect.top
          && previous.box.width === rect.width && previous.box.height === rect.height;
        return same ? previous : { box: { left: rect.left, top: rect.top, width: rect.width, height: rect.height }, radius };
      });
    };
    measure();
    // Layout and the page's own enter animation keep moving for a moment.
    let frame = 0;
    const started = performance.now();
    const follow = () => {
      measure();
      if (performance.now() - started < 700) frame = requestAnimationFrame(follow);
    };
    frame = requestAnimationFrame(follow);
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    observer?.observe(element);
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      cancelAnimationFrame(frame);
      observer?.disconnect();
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [target]);
  return state;
}

function GuideCard({
  step,
  position,
  total,
  last,
  onNext,
  onSkip,
}: {
  step: GuideStep;
  position: number;
  total: number;
  last: boolean;
  onNext: () => void;
  onSkip: () => void;
}) {
  const { box, radius } = useTargetBox(step.target);
  const primaryRef = useRef<HTMLButtonElement | null>(null);
  useEffect(() => primaryRef.current?.focus({ preventScroll: true }), [position]);
  const place = placeBubble(step.target ? box : null, { width: window.innerWidth, height: window.innerHeight }, step.side);
  const skip = step.skip === undefined ? "跳过" : step.skip;
  const lit = step.target && box;

  return (
    <div className="guide" role="dialog" aria-modal="true" aria-label="新手引导">
      {lit ? (
        <span
          className="guide-spot"
          aria-hidden="true"
          style={{
            left: box.left - SPOT_PAD,
            top: box.top - SPOT_PAD,
            width: box.width + SPOT_PAD * 2,
            height: box.height + SPOT_PAD * 2,
            borderRadius: Math.min(radius, 28) + SPOT_PAD,
          }}
        />
      ) : (
        <span className="guide-dim" aria-hidden="true" />
      )}
      <div
        key={position}
        className="guide-card"
        style={{
          left: place.left,
          width: place.width,
          ...(place.side === "above" ? { bottom: place.edge } : { top: place.edge }),
        }}
      >
        {lit ? (
          <span
            className={place.side === "above" ? "guide-arrow is-below" : "guide-arrow"}
            aria-hidden="true"
            style={{ left: place.arrow }}
          />
        ) : null}
        {step.title ? <h2 className="guide-title">{step.title}</h2> : null}
        <p className="guide-text">{step.text}</p>
        <div className="guide-foot">
          {total > 1 ? (
            <span className="guide-dots" role="img" aria-label={`第 ${position} 步，共 ${total} 步`}>
              {Array.from({ length: total }, (_, index) => <span key={index} className={index + 1 === position ? "is-on" : undefined} />)}
            </span>
          ) : null}
          <span className="guide-spacer" />
          {skip === false ? null : <button type="button" className="guide-skip" onClick={onSkip}>{skip}</button>}
          <button ref={primaryRef} type="button" className="guide-next" onClick={onNext}>
            {step.primary ?? (last ? "知道了" : "下一步")}
          </button>
        </div>
      </div>
    </div>
  );
}

