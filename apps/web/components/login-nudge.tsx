"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { authClient } from "../lib/auth-client";
import {
  claimVisitPrompt,
  finishedProgrammeCount,
  loginNudgeSnoozedUntil,
  PROGRAMME_FINISHED_EVENT,
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

  // Shown once the page (not the player) is on screen, if the visit's slot is free.
  useEffect(() => {
    if (phase !== "pending" || hidden) return;
    setPhase(claimVisitPrompt("login") ? "shown" : "none");
  }, [hidden, phase]);

  useEffect(() => {
    if (signedIn) setPhase("none");
  }, [signedIn]);

  if (phase !== "shown" && phase !== "leaving") return null;

  const leave = () => {
    snoozeLoginNudge();
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
        <strong>想让推荐更懂你？</strong>
        <span>登录后会记住你的口味</span>
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
