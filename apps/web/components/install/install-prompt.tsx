"use client";

import { useEffect, useState } from "react";

import {
  acknowledgeInstall,
  countVisit,
  detectPlatform,
  isDesktopPointer,
  isStandalone,
  peekInstallPrompt,
  readInstallState,
  shouldOfferInstall,
  snoozeInstall,
  takeInstallPrompt,
} from "../../lib/install";
import { claimVisitPrompt, visitPrompt } from "../../lib/login-nudge";
import { useOverlay } from "../../lib/overlay-stack";
import { PlusSquareIcon, ShareIcon } from "../icons";
import { LogoMark } from "../logo-mark";
import { Portal } from "../portal";

/** iOS Safari: guided card. Android/Chrome: light banner calling prompt(). */
export function InstallPrompt() {
  const [mode, setMode] = useState<"none" | "ios" | "banner">("none");
  // Plays the 150ms fade-out before the dialog unmounts (MOTION.md §4.3).
  const [leaving, setLeaving] = useState(false);
  const dismiss = () => {
    if (mode === "ios" && !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) setLeaving(true);
    else setMode("none");
  };

  useEffect(() => {
    const visits = countVisit();
    const evaluate = () => {
      const platform = detectPlatform(navigator.userAgent, navigator.maxTouchPoints ?? 0, Boolean(peekInstallPrompt()));
      const show = shouldOfferInstall({ platform, standalone: isStandalone(), desktop: isDesktopPointer(), visits, ...readInstallState() });
      // One one-off prompt per visit: not after the login card, and it holds the slot.
      const allowed = show && visitPrompt() !== "login" && claimVisitPrompt("install");
      setMode(allowed ? (platform === "ios-safari" ? "ios" : "banner") : "none");
    };
    const timer = window.setTimeout(evaluate, 1200);
    const onPrompt = () => window.setTimeout(evaluate, 0);
    window.addEventListener("beforeinstallprompt", onPrompt);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("beforeinstallprompt", onPrompt);
    };
  }, []);

  if (mode === "none") return null;

  const later = () => {
    snoozeInstall();
    dismiss();
  };
  const gotIt = () => {
    acknowledgeInstall();
    dismiss();
  };

  if (mode === "banner") {
    return (
      <div className="install-banner" role="region" aria-label="安装 WaveCast">
        <LogoMark size={36} />
        <span>安装 WaveCast</span>
        <button
          type="button"
          className="install-banner-action"
          onClick={async () => {
            const prompt = takeInstallPrompt();
            if (!prompt) return later();
            await prompt.prompt().catch(() => undefined);
            acknowledgeInstall();
            setMode("none");
          }}
        >
          安装
        </button>
        <button type="button" className="install-banner-close" aria-label="以后再说" onClick={later}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" /></svg>
        </button>
      </div>
    );
  }

  return (
    <IosInstallGuide
      leaving={leaving}
      onLater={later}
      onGotIt={gotIt}
      onLeft={() => {
        setLeaving(false);
        setMode("none");
      }}
    />
  );
}

/**
 * The iOS Safari "add to home screen" guide card. Shown automatically by
 * InstallPrompt, or on request from the account page.
 */
export function IosInstallGuide({
  leaving,
  onLater,
  onGotIt,
  onLeft,
}: {
  /** Plays the 150ms fade-out; onLeft fires when it ends. */
  leaving: boolean;
  onLater: () => void;
  onGotIt: () => void;
  onLeft: () => void;
}) {
  useOverlay(!leaving, onLater);
  return (
    <Portal>
    <div
      className={leaving ? "install-layer is-leaving" : "install-layer"}
      onAnimationEnd={(event) => {
        if (leaving && event.target === event.currentTarget) onLeft();
      }}
    >
      <div className="sheet-scrim" aria-hidden="true" onClick={onLater} />
      <section className="install-card" role="dialog" aria-modal="true" aria-labelledby="install-title">
        <span className="install-logo"><LogoMark size={76} /></span>
        <h2 id="install-title">把 WaveCast 放到主屏幕</h2>
        <p>以后点图标就能直接打开，全屏收听，<br />不用再找网址。</p>
        <ol className="install-steps">
          <li><span className="install-num">1</span><span>点浏览器底部的分享按钮</span><ShareIcon size={22} style={{ color: "#007AFF" }} /></li>
          <li><span className="install-num">2</span><span>选择“添加到主屏幕”</span><PlusSquareIcon size={22} /></li>
          <li><span className="install-num">3</span><span>点右上角的“添加”</span></li>
        </ol>
        <button type="button" className="pill-button install-ok" onClick={onGotIt}>知道了</button>
        <button type="button" className="install-later" onClick={onLater}>以后再说</button>
      </section>
      <div className="install-arrow" aria-hidden="true">
        <span>分享按钮在这里</span>
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M12 4v15M6 13l6 6 6-6" /></svg>
      </div>
    </div>
    </Portal>
  );
}
