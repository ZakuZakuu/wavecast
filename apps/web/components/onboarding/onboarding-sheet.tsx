"use client";

import { useEffect, useState } from "react";

import { api } from "../../lib/api";
import { authClient } from "../../lib/auth-client";
import {
  markOnboardingDoneLocally,
  ONBOARDING_GENRES,
  ONBOARDING_MOMENTS,
  onboardingDoneLocally,
  preferenceUpdate,
} from "../../lib/onboarding";
import { readLocalTaste, writeLocalTaste } from "../../lib/taste";
import type { UserPreferences } from "../../lib/types";
import { BottomSheet } from "../bottom-sheet";

function Check() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="m5 12.5 4.5 4.5L19 7" />
    </svg>
  );
}

function toggle(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((item) => item !== value) : [...list, value];
}

/**
 * First-login taste sheet (two steps). Shown once per account; guests never
 * see it. Choices are saved to the preference API and kept locally for
 * taste_context.
 */
export function OnboardingSheet({
  onFinished,
  force = false,
}: {
  onFinished?: () => void;
  /** Open even when already completed (editing from the account page). */
  force?: boolean;
}) {
  const { data: session, isPending } = authClient.useSession();
  const userId = session?.user?.id ?? null;
  const [open, setOpen] = useState(false);
  const [existing, setExisting] = useState<UserPreferences | null>(null);
  const [step, setStep] = useState<1 | 2>(1);
  const [genres, setGenres] = useState<string[]>([]);
  const [artists, setArtists] = useState("");
  const [moments, setMoments] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isPending || !userId) return;
    if (!force && onboardingDoneLocally(userId)) {
      onFinished?.();
      return;
    }
    let active = true;
    api.userPreferences(userId)
      .then((preferences) => {
        if (!active) return;
        setExisting(preferences);
        if (force) {
          const local = readLocalTaste();
          if (local) {
            setGenres(local.genres);
            setArtists(local.artists);
            setMoments(local.moments);
          }
          setOpen(true);
        } else if (preferences.onboarding_completed) {
          markOnboardingDoneLocally(userId);
          onFinished?.();
        } else {
          setOpen(true);
        }
      })
      .catch(() => {
        // Preferences unavailable: do not block listening with a sheet.
      });
    return () => {
      active = false;
    };
  }, [force, isPending, onFinished, userId]);

  if (!userId || !open) return null;

  const finish = async (choice: { genres: string[]; artists: string; moments: string[] } | null) => {
    if (saving) return;
    setSaving(true);
    setError(null);
    if (choice) writeLocalTaste(choice);
    try {
      await api.saveUserPreferences(preferenceUpdate(existing, choice), userId);
      markOnboardingDoneLocally(userId);
      setOpen(false);
      onFinished?.();
    } catch {
      if (!choice) {
        // A skip should never trap the listener.
        markOnboardingDoneLocally(userId);
        setOpen(false);
        onFinished?.();
      } else {
        setError("保存没有成功，可以再试一次");
      }
    } finally {
      setSaving(false);
    }
  };

  const skip = () => {
    if (force) {
      setOpen(false);
      onFinished?.();
      return;
    }
    void finish(null);
  };

  return (
    <BottomSheet open onClose={skip} label={step === 1 ? "平时爱听什么？" : "一般在什么时候听？"} tone="light" height="min(700px, calc(100dvh - 24px))" className="onboarding">
      <div className="ob-top">
        <span className="ob-step tabular">{step} / 2</span>
        <button type="button" className="ob-skip" onClick={skip} disabled={saving}>跳过</button>
      </div>
      <div className="ob-scroll">
        {step === 1 ? (
          <>
            <h2 className="ob-title">平时爱听什么？</h2>
            <p className="ob-sub">选几个就好，之后随时能在账户里改。</p>
            <div className="ob-chips" role="group" aria-label="音乐风格">
              {ONBOARDING_GENRES.map((genre) => {
                const on = genres.includes(genre);
                return (
                  <button key={genre} type="button" aria-pressed={on} className={on ? "ob-chip is-on" : "ob-chip"} onClick={() => setGenres((list) => toggle(list, genre))}>
                    {on ? <Check /> : null}{genre}
                  </button>
                );
              })}
            </div>
            <label className="ob-field">
              <span>有特别喜欢的歌手吗</span>
              <input type="text" value={artists} onChange={(event) => setArtists(event.target.value)} placeholder="比如：方大同、坂本龙一" maxLength={200} />
            </label>
          </>
        ) : (
          <>
            <h2 className="ob-title">一般在什么时候听？</h2>
            <p className="ob-sub">可以多选。</p>
            <div className="ob-chips" role="group" aria-label="收听场景">
              {ONBOARDING_MOMENTS.map((moment) => {
                const on = moments.includes(moment);
                return (
                  <button key={moment} type="button" aria-pressed={on} className={on ? "ob-chip is-on" : "ob-chip"} onClick={() => setMoments((list) => toggle(list, moment))}>
                    {on ? <Check /> : null}{moment}
                  </button>
                );
              })}
            </div>
          </>
        )}
      </div>
      {error ? <p className="sheet-note is-error" role="alert">{error}</p> : null}
      {step === 1 ? (
        <button type="button" className="pill-button ob-next" onClick={() => setStep(2)}>
          {genres.length ? `继续（已选 ${genres.length} 个）` : "继续"}
        </button>
      ) : (
        <button type="button" className="pill-button ob-next" disabled={saving} onClick={() => void finish({ genres, artists, moments })}>
          {saving ? "正在保存…" : "完成"}
        </button>
      )}
    </BottomSheet>
  );
}
