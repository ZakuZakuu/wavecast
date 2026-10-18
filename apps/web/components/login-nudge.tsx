"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { authClient } from "../lib/auth-client";
import {
  claimVisitPrompt,
  finishedProgrammeCount,
  LOGIN_HINT_EVENT,
  LOGIN_NUDGE_COPY,
  loginNudgeSnoozedUntil,
  PROGRAMME_FINISHED_EVENT,
  type LoginHintCopy,
  shouldShowLoginNudge,
  snoozeLoginNudge,
  visitPrompt,
} from "../lib/login-nudge";

type Phase = "none" | "pending" | "shown" | "leaving";

/**
 * One-off card for guests who just finished their second programme:
 * "想让推荐更懂你？". Sits above the mini player; waits while the player or
 * another full-screen view is open. Enters/leaves like a sheet (MOTION.md
 * §4.2: 350ms ease-enter in, 250ms ease-exit out; fade when reduced).
 */
export function LoginNudge({ hidden }: { hidden: boolean }) {
  const router = useRouter();
  const { data: session } = authClient.useSession();
  const signedIn = Boolean(session?.user);
  const [phase, setPhase] = useState<Phase>("none");
  // A hint the listener asked for is shown as given and does not snooze the one-off card.
  const [asked, setAsked] = useState<LoginHintCopy | null>(null);

  useEffect(() => {
    const onFinished = () => {
      const show = shouldShowLoginNudge({
        signedIn,
        finishedCount: finishedProgrammeCount(),
        snoozedUntil: loginNudgeSnoozedUntil(),
        visitPrompt: visitPrompt(),
        now: Date.now(),
      });
      if (show) setPhase((current) => (current === "none" ? "pending" : current));
    };
    window.addEventListener(PROGRAMME_FINISHED_EVENT, onFinished);
    return () => window.removeEventListener(PROGRAMME_FINISHED_EVENT, onFinished);
  }, [signedIn]);

  useEffect(() => {
    const onHint = (event: Event) => {
      if (signedIn) return;
      setAsked((event as CustomEvent<LoginHintCopy>).detail);
      setPhase("shown");
    };
    window.addEventListener(LOGIN_HINT_EVENT, onHint);
    return () => window.removeEventListener(LOGIN_HINT_EVENT, onHint);
  }, [signedIn]);

  // Shown once the page (not the player) is on screen, if the visit's slot is free.
  useEffect(() => {
    if (phase !== "pending" || hidden) return;
    setPhase(claimVisitPrompt("login") ? "shown" : "none");
  }, [hidden, phase]);

  useEffect(() => {
    if (signedIn) setPhase("none");
  }, [signedIn]);

  useEffect(() => {
    if (phase === "none") setAsked(null);
  }, [phase]);

  if (phase !== "shown" && phase !== "leaving") return null;

  const copy = asked ?? LOGIN_NUDGE_COPY;
  const leave = () => {
    if (!asked) snoozeLoginNudge();
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) setPhase("none");
    else setPhase("leaving");
  };

  return (
    <section
      className={phase === "leaving" ? "login-nudge is-leaving" : "login-nudge"}
      hidden={hidden}
      aria-label="登录提示"
      onAnimationEnd={(event) => {
        if (phase === "leaving" && event.target === event.currentTarget) setPhase("none");
      }}
    >
      <p className="login-nudge-copy">
        <strong>{copy.title}</strong>
        <span>{copy.note}</span>
      </p>
      <div className="login-nudge-actions">
        <button type="button" className="login-nudge-later" onClick={leave}>以后再说</button>
        <button
          type="button"
          className="login-nudge-go"
          onClick={() => {
            leave();
            router.push("/account");
          }}
        >
          登录
        </button>
      </div>
    </section>
  );
}
