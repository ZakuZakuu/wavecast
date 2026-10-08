"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, useSyncExternalStore } from "react";

import {
  avatarInitial,
  libraryProgrammeCount,
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
import { EmailLogin } from "./account/email-login";
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

function LoginView({ availability }: { availability: AuthAvailability | null }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<SocialProvider | null>(null);
  const [emailBusy, setEmailBusy] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const providers = signInProviders(availability);
  const emailEnabled = Boolean(availability?.enabled && availability.emailOtp);
  const known = availability !== null;
  const signInOff = known && providers.length === 0 && !emailEnabled;

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

  // Waiting for the emailed code, the page is only about the code.
  const showSocial = providers.length > 0 && !verifying;

  return (
    <div className="acct acct-login">
      <div className="acct-body">
        <BackButton />
        <div className="login-brand">
          <span className="login-logo"><LogoMark size={72} /></span>
          <h1>WaveCast</h1>
          <p>轻主持的 AI 音乐电台</p>
        </div>

        <div className="login-actions">
          {emailEnabled ? <EmailLogin disabled={busy !== null} onBusyChange={setEmailBusy} onStepChange={setVerifying} onSuccess={() => {
            clearApiAuthToken();
            router.push("/onboarding");
            router.refresh();
          }} /> : null}
          {showSocial && emailEnabled ? <p className="login-divider">或</p> : null}
          {showSocial ? (
            <div className="login-social">
              {providers.includes("google") ? (
                <button type="button" className="login-button is-social" aria-label="使用 Google 继续" disabled={busy !== null || emailBusy} onClick={() => void signIn("google")}>
                  <GoogleMark />
                  {busy === "google" ? "跳转中…" : "Google"}
                </button>
              ) : null}
              {providers.includes("github") ? (
                <button type="button" className="login-button is-social" aria-label="使用 GitHub 继续" disabled={busy !== null || emailBusy} onClick={() => void signIn("github")}>
                  <GitHubMark />
                  {busy === "github" ? "跳转中…" : "GitHub"}
                </button>
              ) : null}
            </div>
          ) : null}
          {signInOff ? <p className="login-off" role="status">当前版本暂不支持登录，可以直接开始收听</p> : null}
          {error ? <p className="login-error" role="alert">{error}</p> : null}
          <button type="button" className="login-skip" onClick={() => router.push("/")}>
            {signInOff ? "开始收听" : "先不登录，直接收听"}
          </button>
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
  const [editingTaste, setEditingTaste] = useState(false);
  const [taste, setTaste] = useState<string | null>(null);
  const [installRow, setInstallRow] = useState<InstallRow>(null);
  const [guide, setGuide] = useState<"open" | "leaving" | null>(null);
  const count = useLibraryCount();

  useEffect(() => {
    setTaste(tasteSummary(readLocalTaste()));
  }, [editingTaste]);

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
          <p>{email ?? ""}</p>
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
