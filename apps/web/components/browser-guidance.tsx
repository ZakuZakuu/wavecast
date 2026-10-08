"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { browserGuidance } from "../lib/browser-guidance";
import { useOverlay } from "../lib/overlay-stack";
import { LogoMark } from "./logo-mark";
import { Portal } from "./portal";

const DISMISSED = "wavecast:wechat-guide-dismissed";

export function BrowserGuidance() {
  const [kind, setKind] = useState<ReturnType<typeof browserGuidance>>("none");
  const [open, setOpen] = useState(false);
  const [url, setUrl] = useState("");
  const [copyState, setCopyState] = useState<"idle" | "copied" | "manual">("idle");
  const [desktopHidden, setDesktopHidden] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const panelRef = useRef<HTMLElement | null>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const focusPanel = useCallback((node: HTMLElement | null) => {
    panelRef.current = node;
    node?.focus({ preventScroll: true });
  }, []);

  useEffect(() => {
    const detected = browserGuidance(navigator.userAgent, navigator.maxTouchPoints);
    setKind(detected);
    setUrl(window.location.href);
    if (detected.startsWith("wechat")) {
      let dismissed = false;
      try { dismissed = sessionStorage.getItem(DISMISSED) === "1"; } catch { /* Still show guidance when storage is unavailable. */ }
      setOpen(!dismissed);
    }
  }, []);

  const dismiss = () => {
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) setOpen(false);
    else setLeaving(true);
    try { sessionStorage.setItem(DISMISSED, "1"); } catch { /* Dismissal still works for this mount. */ }
  };

  useOverlay(open && !leaving, dismiss);

  useEffect(() => {
    if (!open) return;
    returnFocus.current = document.activeElement as HTMLElement | null;
    const trap = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const panel = panelRef.current;
      const buttons = panel?.querySelectorAll<HTMLElement>("button, input");
      if (!panel || !buttons?.length) return;
      const first = buttons[0];
      const last = buttons[buttons.length - 1];
      if (!panel.contains(document.activeElement) || document.activeElement === panel || (event.shiftKey && document.activeElement === first)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault(); first.focus();
      }
    };
    document.addEventListener("keydown", trap);
    return () => {
      document.removeEventListener("keydown", trap);
      returnFocus.current?.focus({ preventScroll: true });
    };
  }, [open]);

  useEffect(() => {
    if (!leaving) return;
    const timer = window.setTimeout(() => { setOpen(false); setLeaving(false); }, 180);
    return () => window.clearTimeout(timer);
  }, [leaving]);

  if (kind === "desktop") {
    return desktopHidden ? null : (
      <aside className="browser-desktop-hint" aria-label="浏览器体验建议">
        <span>推荐使用 iPhone Safari 体验，桌面端建议使用 Chrome 或 Edge。</span>
        <button type="button" aria-label="关闭浏览器建议" onClick={() => setDesktopHidden(true)}>×</button>
      </aside>
    );
  }
  if (!kind.startsWith("wechat")) return null;

  const copy = async () => {
    // Preserve the current programme path when the user navigated since opening.
    const current = window.location.href;
    setUrl(current);
    try {
      await navigator.clipboard.writeText(current);
      setCopyState("copied");
    } catch {
      setCopyState("manual");
    }
  };

  if (!open) return null;
  return (
    <Portal>
      <div className={leaving ? "install-layer browser-guide-layer is-leaving" : "install-layer browser-guide-layer"}>
        <div className="sheet-scrim" aria-hidden="true" onClick={dismiss} />
        <section className="install-card browser-guide-card" role="dialog" aria-modal="true" aria-labelledby="browser-guide-title" tabIndex={-1} ref={focusPanel}>
          <span className="install-logo"><LogoMark size={76} /></span>
          <h2 id="browser-guide-title">换个浏览器，安心收听</h2>
        <p>微信内播放可能不顺畅。{kind === "wechat-ios" ? "推荐用 Safari 收听。" : "推荐用 Chrome、Edge 或系统浏览器收听。"}</p>
        <ol className="install-steps">
          <li><span className="install-num">1</span><span>点微信右上角的「···」菜单</span></li>
          <li><span className="install-num">2</span><span>{kind === "wechat-ios" ? "选择在 Safari 或浏览器中打开" : "选择在浏览器中打开"}</span></li>
        </ol>
        <p className="browser-guide-note">没有这个选项？复制链接，再粘贴到浏览器。网页无法代你切换浏览器。</p>
        <button type="button" className="pill-button install-ok" onClick={copy}>{copyState === "copied" ? "已复制链接" : "复制当前链接"}</button>
        {copyState === "manual" ? <label className="browser-guide-manual">请长按或选中下方链接复制<input aria-label="当前页面链接" readOnly value={url} onFocus={(event) => event.currentTarget.select()} /></label> : null}
        <span role="status" className="browser-guide-note">{copyState === "copied" ? "打开浏览器，粘贴链接就能继续。" : copyState === "manual" ? "自动复制不可用，请手动复制。" : ""}</span>
        <button type="button" className="install-later" onClick={dismiss}>继续体验</button>
        </section>
        <div className="browser-guide-arrow" aria-hidden="true"><span>菜单在右上角</span><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M4 20L20 4M10 4h10v10" /></svg></div>
      </div>
    </Portal>
  );
}
