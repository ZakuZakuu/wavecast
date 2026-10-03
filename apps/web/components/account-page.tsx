"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, useSyncExternalStore } from "react";

import {
  avatarInitial,
  libraryProgrammeCount,
  providerLabel,
  signInProviders,
  tasteSummary,
  type AuthAvailability,
  type SocialProvider,
} from "../lib/account";
import { authClient, clearApiAuthToken } from "../lib/auth-client";
import { detectPlatform, isStandalone, peekInstallPrompt, takeInstallPrompt, acknowledgeInstall } from "../lib/install";
import { lastTabPathOr } from "../lib/nav-memory";
import { readLocalTaste } from "../lib/taste";
import { emptyUserLibrary, readUserLibrary, subscribeUserLibrary } from "../lib/user-library";
import { GitHubMark, GoogleMark } from "./account/brand-icons";
import { IosInstallGuide } from "./install/install-prompt";
import { LogoMark } from "./logo-mark";
import { OnboardingSheet } from "./onboarding/onboarding-sheet";

function BackButton() {
  const router = useRouter();
  return (
    <button type="button" className="acct-back" aria-label="返回" onClick={() => router.push(lastTabPathOr("/"))}>
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m15 6-6 6 6 6" /></svg>
    </button>
  );
}

function Chevron() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#C7C7CC" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m9 6 6 6-6 6" /></svg>
  );
}

/** /account: the login page for guests (Frost-Login), the account page when signed in (Frost-Account). */
export function AccountPage() {
  const { data: session, isPending } = authClient.useSession();
  const [availability, setAvailability] = useState<AuthAvailability | null>(null);

  useEffect(() => {
    let active = true;
    fetch("/api/auth/providers")
      .then((response) => response.json())
      .then((value: AuthAvailability) => {
        if (active) setAvailability(value);
      })
      .catch(() => {
        if (active) setAvailability({ enabled: false, providers: [] });
      });
    return () => {
      active = false;
    };
  }, []);

  if (isPending) {
    return <div className="acct" aria-busy="true"><div className="acct-body"><BackButton /></div></div>;
  }
  if (session?.user) {
    return <AccountView name={session.user.name} email={session.user.email} />;
  }
  return <LoginView availability={availability} />;
}

const BENEFITS = [
  {
    title: "节目库跟着账号走",
    line: "换了设备，也能接着上次的地方听",
    tint: "rgba(62, 156, 140, .16)",
    color: "#2E7D70",
    icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinejoin="round"><rect x="4" y="4" width="4" height="16" rx="1" /><rect x="10" y="4" width="4" height="16" rx="1" /><path d="m16 5.4 3.4-0.9 2.9 13.9-3.4 0.9z" /></svg>,
  },
  {
    title: "推荐越来越准",
    line: "按你的口味和收听记录准备节目",
    tint: "rgba(232, 131, 74, .16)",
    color: "#B5562A",
    icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3.5l2.4 5 5.4.6-4 3.7 1.1 5.4L12 15.5l-4.9 2.7 1.1-5.4-4-3.7 5.4-.6z" /></svg>,
  },
  {
    title: "调过的节目都留着",
    line: "随时回来重听",
    tint: "rgba(110, 98, 182, .16)",
    color: "#5A4FA0",
    icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"><rect x="2.5" y="8" width="19" height="9" rx="4.5" /><path d="M13.5 5.5v13" /></svg>,
  },
];

function LoginView({ availability }: { availability: AuthAvailability | null }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<SocialProvider | null>(null);
  const providers = signInProviders(availability);
  const known = availability !== null;
  const signInOff = known && providers.length === 0;

  const signIn = async (provider: SocialProvider) => {
    setError(null);
    setBusy(provider);
    const result = await authClient.signIn.social({ provider, callbackURL: "/onboarding" }).catch(() => ({ error: true }));
    if (result.error) {
      setError("暂时无法登录，请稍后再试。");
      setBusy(null);
    } else {
      clearApiAuthToken();
    }
  };

  return (
    <div className="acct acct-login">
      <span className="glow" aria-hidden="true" style={{ left: -120, top: -80, width: 360, height: 360, background: "#E8834A", opacity: 0.22 }} />
      <span className="glow" aria-hidden="true" style={{ right: -140, top: 120, width: 340, height: 340, background: "#6E62B6", opacity: 0.2 }} />
      <span className="glow" aria-hidden="true" style={{ left: 20, top: 330, width: 300, height: 260, background: "#3E9C8C", opacity: 0.14 }} />
      <div className="acct-body">
        <BackButton />
        <div className="login-brand">
          <span className="login-logo"><LogoMark size={96} /></span>
          <h1>WaveCast</h1>
          <p>轻主持的 AI 音乐电台</p>
        </div>

        <ul className="login-benefits">
          {BENEFITS.map((benefit) => (
            <li key={benefit.title}>
              <span className="login-benefit-icon" aria-hidden="true" style={{ background: benefit.tint, color: benefit.color }}>{benefit.icon}</span>
              <span className="login-benefit-copy">
                <span className="login-benefit-title">{benefit.title}</span>
                <span className="login-benefit-line">{benefit.line}</span>
              </span>
            </li>
          ))}
        </ul>

        <div className="login-actions">
          {providers.includes("github") ? (
            <button type="button" className="login-button is-github" disabled={busy !== null} onClick={() => void signIn("github")}>
              <GitHubMark />
              {busy === "github" ? "正在跳转…" : "使用 GitHub 继续"}
            </button>
          ) : null}
          {providers.includes("google") ? (
            <button type="button" className="login-button is-google" disabled={busy !== null} onClick={() => void signIn("google")}>
              <GoogleMark />
              {busy === "google" ? "正在跳转…" : "使用 Google 继续"}
            </button>
          ) : null}
          {signInOff ? <p className="login-off" role="status">当前版本暂不支持登录，可以直接开始收听</p> : null}
          {error ? <p className="login-error" role="alert">{error}</p> : null}
          <button type="button" className="login-skip" onClick={() => router.push("/")}>
            {signInOff ? "开始收听" : "先不登录，直接收听"}
          </button>
          {signInOff ? null : <p className="login-foot">登录只用于同步节目库和推荐。</p>}
        </div>
      </div>
    </div>
  );
}

function useLibraryCount(): number {
  return useSyncExternalStore(
    subscribeUserLibrary,
    () => libraryProgrammeCount(readUserLibrary()),
    () => libraryProgrammeCount(emptyUserLibrary()),
  );
}

type InstallRow = "ios" | "prompt" | null;

function AccountView({ name, email }: { name: string; email: string | null | undefined }) {
  const [provider, setProvider] = useState<string | null>(null);
  const [editingTaste, setEditingTaste] = useState(false);
  const [taste, setTaste] = useState<string | null>(null);
  const [installRow, setInstallRow] = useState<InstallRow>(null);
  const [guide, setGuide] = useState<"open" | "leaving" | null>(null);
  const count = useLibraryCount();

  useEffect(() => {
    setTaste(tasteSummary(readLocalTaste()));
  }, [editingTaste]);

  useEffect(() => {
    let active = true;
    authClient.listAccounts()
      .then((result) => {
        const accounts = (result as { data?: Array<{ providerId?: string; provider?: string }> | null }).data ?? [];
        const first = accounts.find((account) => account.providerId === "github" || account.providerId === "google") ?? accounts[0];
        if (active) setProvider(first?.providerId ?? first?.provider ?? null);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);

  // Only where installing is possible and not done yet.
  useEffect(() => {
    if (isStandalone()) return;
    const platform = detectPlatform(navigator.userAgent, navigator.maxTouchPoints ?? 0, Boolean(peekInstallPrompt()));
    setInstallRow(platform === "ios-safari" ? "ios" : platform === "installable" ? "prompt" : null);
  }, []);

  const install = async () => {
    if (installRow === "ios") {
      setGuide("open");
      return;
    }
    const prompt = takeInstallPrompt();
    if (!prompt) return;
    await prompt.prompt().catch(() => undefined);
    acknowledgeInstall();
    setInstallRow(null);
  };

  const closeGuide = () => {
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) setGuide(null);
    else setGuide("leaving");
  };

  const signOut = async () => {
    await authClient.signOut();
    clearApiAuthToken();
  };

  return (
    <div className="acct">
      <div className="acct-body">
        <BackButton />
        <div className="acct-profile">
          <span className="acct-avatar" aria-hidden="true">{avatarInitial(name, email)}</span>
          <h1>{name || email}</h1>
          <p>{providerLabel(provider) ?? email ?? ""}</p>
        </div>

        <h2 className="acct-group-title">收听</h2>
        <ul className="acct-group">
          <li>
            <button type="button" className="acct-row is-tall" onClick={() => setEditingTaste(true)}>
              <span className="acct-row-copy">
                <span className="acct-row-title">收听偏好</span>
                <span className="acct-row-sub">{taste ?? "还没有设置"}</span>
              </span>
              <Chevron />
            </button>
          </li>
          <li>
            <Link href="/library" className="acct-row is-tall">
              <span className="acct-row-copy">
                <span className="acct-row-title">节目库</span>
                <span className="acct-row-sub">{count ? `${count} 档节目，已同步` : "还没有节目"}</span>
              </span>
              <Chevron />
            </Link>
          </li>
        </ul>

        <h2 className="acct-group-title">其他</h2>
        <ul className="acct-group">
          {installRow ? (
            <li>
              <button type="button" className="acct-row" onClick={() => void install()}>
                <span className="acct-row-title">添加到主屏幕</span>
                <Chevron />
              </button>
            </li>
          ) : null}
          <li>
            <div className="acct-row is-static">
              <span className="acct-row-title">版本</span>
              <span className="acct-row-value">初赛版</span>
            </div>
          </li>
        </ul>

        <button type="button" className="acct-signout" onClick={() => void signOut()}>退出登录</button>
      </div>
      {editingTaste ? <OnboardingSheet force onFinished={() => setEditingTaste(false)} /> : null}
      {guide ? (
        <IosInstallGuide
          leaving={guide === "leaving"}
          onLater={closeGuide}
          onGotIt={() => {
            acknowledgeInstall();
            closeGuide();
          }}
          onLeft={() => setGuide(null)}
        />
      ) : null}
    </div>
  );
}
