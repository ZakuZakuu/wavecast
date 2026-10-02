"use client";

import { useEffect, useState } from "react";

import { AppShell } from "./app-shell";
import { OnboardingSheet } from "./onboarding/onboarding-sheet";
import { authClient, clearApiAuthToken } from "../lib/auth-client";

type AuthAvailability = { enabled: boolean; providers: string[] };

export function AccountPage() {
  const { data: session, isPending } = authClient.useSession();
  const [availability, setAvailability] = useState<AuthAvailability>({
    enabled: false,
    providers: [],
  });
  const [error, setError] = useState<string | null>(null);
  const [editingTaste, setEditingTaste] = useState(false);

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

  const signIn = async (provider: "google" | "github") => {
    setError(null);
    const result = await authClient.signIn.social({ provider, callbackURL: "/onboarding" });
    if (result.error) setError("暂时无法登录，请稍后再试。");
    else clearApiAuthToken();
  };

  const signOut = async () => {
    await authClient.signOut();
    clearApiAuthToken();
  };

  return (
    <AppShell>
      <div className="account">
        <header className="home-head">
          <h1 className="page-title">账户</h1>
          <span className="avatar" aria-hidden="true">
            {session?.user?.name?.trim().slice(0, 1) || (
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><circle cx="12" cy="9" r="3.6" /><path d="M5.5 19.5a6.5 6.5 0 0 1 13 0" /></svg>
            )}
          </span>
        </header>

        {isPending ? <p className="inline-note" role="status">正在读取账户状态…</p> : null}
        {!isPending && session?.user ? (
          <section className="account-group">
            <div className="account-row">
              <strong>{session.user.name}</strong>
              {session.user.email ? <span>{session.user.email}</span> : null}
            </div>
            <p className="account-note">节目库已同步到账号，可以在其他设备继续听。</p>
            <button type="button" className="account-action" onClick={() => setEditingTaste(true)}>修改收听偏好</button>
            <button type="button" className="account-action is-danger" onClick={() => void signOut()}>退出登录</button>
          </section>
        ) : null}

        {!isPending && !session?.user ? (
          <section className="account-group">
            <div className="account-row">
              <strong>现在就可以开始听</strong>
              <span>调频和收听都不需要登录。登录后可以把节目库带到其他设备。</span>
            </div>
            {availability.providers.includes("google") ? (
              <button type="button" className="account-action" onClick={() => void signIn("google")}>使用 Google 继续</button>
            ) : null}
            {availability.providers.includes("github") ? (
              <button type="button" className="account-action" onClick={() => void signIn("github")}>使用 GitHub 继续</button>
            ) : null}
            {availability.enabled && availability.providers.length === 0 ? (
              <p className="account-note">登录方式暂未开放，可以继续以访客身份使用。</p>
            ) : null}
          </section>
        ) : null}
        {error ? <p className="inline-note is-error" role="alert">{error}</p> : null}
      </div>
      {editingTaste ? <OnboardingSheet force onFinished={() => setEditingTaste(false)} /> : null}
    </AppShell>
  );
}
