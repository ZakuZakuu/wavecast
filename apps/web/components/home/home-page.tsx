"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { api } from "../../lib/api";
import { authClient } from "../../lib/auth-client";
import { programmeCover } from "../../lib/cover/programme-cover";
import { formatFreq, rememberProgrammeStation, stationForProgramme, STATIONS } from "../../lib/stations";
import type { ProgramIdea, Seed } from "../../lib/types";
import { AppShell } from "../app-shell";
import { TypeCover } from "../cover/type-cover";
import { InstallPrompt } from "../install/install-prompt";
import { OnboardingSheet } from "../onboarding/onboarding-sheet";
import { useNowPlaying } from "../player/playback-provider";

type Pick = {
  key: string;
  id: string;
  title: string;
  minutes: number | null;
  onOpen: () => void;
  busy: boolean;
};

function PickCard({ pick }: { pick: Pick }) {
  const station = stationForProgramme(pick.id, pick.title);
  const cover = programmeCover({ id: pick.id, title: pick.title, stationId: station.id });
  const meta = pick.minutes ? `${station.name}，约 ${pick.minutes} 分钟` : station.name;
  return (
    <button
      type="button"
      className="pick"
      aria-label={`${pick.title}，${meta}`}
      onClick={pick.onOpen}
      disabled={pick.busy}
    >
      <span className="pick-cover">
        <TypeCover params={cover.params} radius={0} />
      </span>
      {cover.titleBelow ? <span className="pick-title">{pick.title}</span> : null}
      <span className="pick-meta">{pick.busy ? "正在准备…" : meta}</span>
    </button>
  );
}

export function HomePage({ onOnboardingFinished }: { onOnboardingFinished?: () => void } = {}) {
  const router = useRouter();
  const np = useNowPlaying();
  const { data: session, isPending: sessionPending } = authClient.useSession();
  const user = session?.user ?? null;
  const [seeds, setSeeds] = useState<Seed[] | null>(null);
  const [ideas, setIdeas] = useState<ProgramIdea[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  useEffect(() => {
    api.seeds()
      .then(setSeeds)
      .catch(() => setSeeds([]));
  }, []);

  useEffect(() => {
    if (sessionPending) return;
    if (!user) {
      setIdeas(null);
      return;
    }
    let active = true;
    api.recommendations(user.id)
      .then((value) => {
        if (active) setIdeas(value);
      })
      .catch(() => {
        if (active) setIdeas([]);
      });
    return () => {
      active = false;
    };
  }, [sessionPending, user]);

  const openIdea = async (idea: ProgramIdea) => {
    if (busyId || !user) return;
    setBusyId(idea.id);
    setError(null);
    try {
      const batch = await api.materializeRecommendation(idea.id, user.id);
      const proposal = batch.proposals[0];
      if (!proposal) throw new Error();
      rememberProgrammeStation(proposal.id, stationForProgramme(idea.id, idea.title).id);
      router.push(`/episode/${proposal.id}`);
    } catch {
      setError("这档节目暂时开不了，换一档试试");
      setBusyId(null);
    }
  };

  // Personalised ideas when signed in; otherwise (or when empty) the seeds — rendered once.
  const picks: Pick[] = useMemo(() => {
    if (ideas && ideas.length) {
      return ideas.map((idea) => ({
        key: "idea:" + idea.id,
        id: idea.id,
        title: idea.title,
        minutes: null,
        busy: busyId === idea.id,
        onOpen: () => void openIdea(idea),
      }));
    }
    return (seeds ?? []).map((seed) => ({
      key: "seed:" + seed.id,
      id: seed.id,
      title: seed.title,
      minutes: Math.max(1, Math.round(seed.estimated_duration_seconds / 60)),
      busy: false,
      onOpen: () => {
        rememberProgrammeStation(seed.id, stationForProgramme(seed.id, seed.title).id);
        router.push(`/episode/${seed.id}`);
      },
    }));
  }, [busyId, ideas, router, seeds, user]);

  const loading = seeds === null || (Boolean(user) && ideas === null);
  const glow = np?.station?.light ?? "#5C7CE0";
  const initial = user?.name?.trim().slice(0, 1) || user?.email?.slice(0, 1)?.toUpperCase() || null;

  return (
    <AppShell
      background={<span className="glow" aria-hidden="true" style={{ left: -100, top: -160, width: 420, height: 340, background: glow, opacity: 0.14 }} />}
    >
      <div className="home">
        <header className="home-head">
          <h1 className="page-title">首页</h1>
          <Link href="/account" className="avatar" aria-label="账户">
            {initial ?? (
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true"><circle cx="12" cy="9" r="3.6" /><path d="M5.5 19.5a6.5 6.5 0 0 1 13 0" /></svg>
            )}
          </Link>
        </header>

        <section className="home-section" aria-labelledby="home-stations">
          <h2 id="home-stations" className="section-title">电台</h2>
          <div className="station-row">
            {STATIONS.map((station) => (
              <Link
                key={station.id}
                href={`/tune?station=${station.id}`}
                className="station-card"
                style={{ background: station.deep }}
                aria-label={`FM ${formatFreq(station.freq)} ${station.name}，${station.line}`}
              >
                <span className="station-card-freq tabular">{formatFreq(station.freq)}</span>
                <span className="station-card-copy">
                  <span className="station-card-name">{station.name}</span>
                  <span className="station-card-line">{station.line}</span>
                </span>
              </Link>
            ))}
          </div>
        </section>

        <section className="home-section" aria-labelledby="home-picks">
          <h2 id="home-picks" className="section-title">猜你想听</h2>
          {error ? <p className="inline-note" role="alert">{error}</p> : null}
          <div className="pick-grid">
            {picks.map((pick) => <PickCard key={pick.key} pick={pick} />)}
            {loading && !picks.length
              ? Array.from({ length: 4 }).map((_, index) => <span key={index} className="pick-skeleton" aria-hidden="true" />)
              : null}
          </div>
          {!loading && !picks.length ? (
            <p className="inline-note">还没有可以推荐的节目。<Link href="/tune">去调一档</Link></p>
          ) : null}
        </section>
      </div>
      <OnboardingSheet onFinished={onOnboardingFinished} />
      <InstallPrompt />
    </AppShell>
  );
}
