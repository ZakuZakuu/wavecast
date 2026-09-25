"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AppShell } from "./app-shell";
import { authClient, clearApiAuthToken } from "../lib/auth-client";

type AuthAvailability = { enabled: boolean; providers: string[] };

export function AccountPage() {
  const { data: session, isPending } = authClient.useSession();
  const [availability, setAvailability] = useState<AuthAvailability>({
    enabled: false,
    providers: [],
  });
  const [error, setError] = useState<string | null>(null);

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
    const result = await authClient.signIn.social({ provider, callbackURL: "/account" });
    if (result.error) setError("暂时无法登录，请稍后再试。");
    else clearApiAuthToken();
  };

  const signOut = async () => {
    await authClient.signOut();
    clearApiAuthToken();
  };

  return (
    <AppShell>
      <div className="page-header account-header">
        <div><p className="program-kicker">YOUR WAVECAST</p><h1>账户</h1></div>
        <span className="profile-dot" aria-hidden="true">{session?.user.name?.slice(0, 1) ?? "访"}</span>
      </div>

      {isPending ? <p className="account-status">正在读取账户状态…</p> : null}
      {!isPending && session?.user ? (
        <section className="account-card">
          <p className="program-kicker">已登录</p>
          <h2>{session.user.name}</h2>
          {session.user.email ? <p>{session.user.email}</p> : null}
          <p className="account-benefit">你的节目库已同步到账号，可在其他设备继续使用。</p>
          <button type="button" className="account-secondary" onClick={() => void signOut()}>
            退出登录
          </button>
        </section>
      ) : null}

      {!isPending && !session?.user ? (
        <section className="account-card">
          <p className="program-kicker">访客模式</p>
          <h2>现在就可以开始听</h2>
          <p className="account-benefit">
            浏览、收藏、调频和收听都不需要登录。登录后可以把节目库带到其他设备。
          </p>
          {availability.providers.includes("google") ? (
            <button type="button" className="account-primary" onClick={() => void signIn("google")}>
              使用 Google 继续
            </button>
          ) : null}
          {availability.providers.includes("github") ? (
            <button type="button" className="account-secondary" onClick={() => void signIn("github")}>
              使用 GitHub 继续
            </button>
          ) : null}
          {availability.enabled && availability.providers.length === 0 ? (
            <p className="account-status">登录方式暂未开放，你仍可继续以访客身份使用。</p>
          ) : null}
        </section>
      ) : null}
      {error ? <p className="inline-error" role="alert">{error}</p> : null}
      <Link className="account-back" href="/">回到为你推荐</Link>
    </AppShell>
  );
}
