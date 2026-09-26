"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import React, { useEffect, useState } from "react";

import { api } from "../lib/api";
import type {
  DiscoveryLevel,
  UserGenre,
  UserMood,
  UserPreferences,
} from "../lib/types";
import { AppShell } from "./app-shell";
import { authClient } from "../lib/auth-client";

const GENRES: UserGenre[] = [
  "City Pop",
  "R&B",
  "Jazz",
  "Electronic",
  "Hip-Hop",
  "Rock",
  "Classical",
];
const MOODS: UserMood[] = ["Chill", "Focus", "Late Night", "Discovery"];
const DISCOVERY: Array<{ value: DiscoveryLevel; label: string }> = [
  { value: "SAFE", label: "熟悉一点" },
  { value: "BALANCED", label: "平衡探索" },
  { value: "ADVENTUROUS", label: "多发现新声音" },
];

export function OnboardingPage() {
  const router = useRouter();
  const { data: session, isPending } = authClient.useSession();
  const [preferences, setPreferences] = useState<UserPreferences | null>(null);
  const [genres, setGenres] = useState<UserGenre[]>([]);
  const [moods, setMoods] = useState<UserMood[]>([]);
  const [discoveryLevel, setDiscoveryLevel] = useState<DiscoveryLevel>("BALANCED");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isPending || !session?.user) return;
    let active = true;
    setLoading(true);
    api.userPreferences(session.user.id)
      .then((value) => {
        if (!active) return;
        if (value.onboarding_completed) {
          router.replace("/");
          return;
        }
        setPreferences(value);
        setGenres(value.genres);
        setMoods(value.moods);
        setDiscoveryLevel(value.discovery_level);
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "读取偏好失败");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [isPending, router, session?.user?.id]);

  const submit = async (skip = false) => {
    if (saving) return;
    setSaving(true);
    setError(null);
    try {
      if (!session?.user) throw new Error("登录状态已失效");
      await api.saveUserPreferences({
        genres: skip ? [] : genres,
        artists: preferences?.artists ?? [],
        moods: skip ? [] : moods,
        contexts: preferences?.contexts ?? [],
        discovery_level: skip ? "BALANCED" : discoveryLevel,
        onboarding_completed: true,
      }, session.user.id);
      router.replace("/");
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "保存失败，请稍后再试");
    } finally {
      setSaving(false);
    }
  };

  const toggleGenre = (genre: UserGenre) => {
    setGenres((current) =>
      current.includes(genre) ? current.filter((item) => item !== genre) : [...current, genre],
    );
  };
  const toggleMood = (mood: UserMood) => {
    setMoods((current) =>
      current.includes(mood) ? current.filter((item) => item !== mood) : [...current, mood],
    );
  };

  return (
    <AppShell>
      <div className="page-header">
        <div><p className="program-kicker">MAKE IT YOURS</p><h1>选出你的氛围</h1></div>
      </div>
      {isPending || loading ? <p className="account-status">正在准备你的偏好…</p> : null}
      {session?.user && error && !preferences ? (
        <p className="inline-error" role="alert">{error}</p>
      ) : null}
      {!isPending && !session?.user ? (
        <section className="onboarding-card">
          <h2>兴趣设置是可选的</h2>
          <p>登录后可以保存你的音乐偏好；访客仍可直接使用 WaveCast。</p>
          <Link className="account-primary onboarding-link" href="/account">前往账户</Link>
        </section>
      ) : null}
      {session?.user && !loading && preferences && !preferences.onboarding_completed ? (
        <section className="onboarding-card" aria-label="Pick your vibe">
          <p className="onboarding-intro">Pick your vibe</p>
          <h2>从你喜欢的声音开始</h2>
          <p>选几项就好，之后可以跳过；这些偏好只用于让节目更贴近你。</p>
          <fieldset className="onboarding-field">
            <legend>喜欢的音乐</legend>
            <div className="chip-row">
              {GENRES.map((genre) => (
                <button
                  aria-pressed={genres.includes(genre)}
                  className={genres.includes(genre) ? "choice-chip selected" : "choice-chip"}
                  key={genre}
                  onClick={() => toggleGenre(genre)}
                  type="button"
                >
                  {genre}
                </button>
              ))}
            </div>
          </fieldset>
          <fieldset className="onboarding-field">
            <legend>此刻的心情</legend>
            <div className="chip-row">
              {MOODS.map((mood) => (
                <button
                  aria-pressed={moods.includes(mood)}
                  className={moods.includes(mood) ? "choice-chip selected" : "choice-chip"}
                  key={mood}
                  onClick={() => toggleMood(mood)}
                  type="button"
                >
                  {mood}
                </button>
              ))}
            </div>
          </fieldset>
          <fieldset className="onboarding-field">
            <legend>你希望发现多少新声音？</legend>
            <div className="discovery-options">
              {DISCOVERY.map((option) => (
                <button
                  aria-pressed={discoveryLevel === option.value}
                  className={discoveryLevel === option.value ? "discovery-option selected" : "discovery-option"}
                  key={option.value}
                  onClick={() => setDiscoveryLevel(option.value)}
                  type="button"
                >
                  {option.label}
                </button>
              ))}
            </div>
          </fieldset>
          {error ? <p className="inline-error" role="alert">{error}</p> : null}
          <div className="onboarding-actions">
            <button className="account-secondary" disabled={saving} onClick={() => void submit(true)} type="button">
              {saving ? "正在保存…" : "跳过，先去听"}
            </button>
            <button className="account-primary" disabled={saving} onClick={() => void submit(false)} type="button">
              {saving ? "正在保存…" : "完成"}
            </button>
          </div>
        </section>
      ) : null}
    </AppShell>
  );
}
