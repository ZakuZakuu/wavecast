"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { api } from "../../lib/api";
import { openPlayer } from "../../lib/player-nav";
import { authClient } from "../../lib/auth-client";
import { programmeCover, rememberCoverSource } from "../../lib/cover/programme-cover";
import { dedupeByTitle, pickMeta, RECOMMENDATION_MINUTES } from "../../lib/home-picks";
import { FEATURED_PROGRAMMES, featuredDurationIntent, type FeaturedProgramme } from "../../lib/featured";
import {
  formatFreq,
  rememberProgrammeStation,
  stationById,
  stationForProgramme,
  STATIONS,
  type StationId,
} from "../../lib/stations";
import type { ProgramIdea, Seed } from "../../lib/types";
import { AppShell } from "../app-shell";
import { TypeCover } from "../cover/type-cover";
import { InstallPrompt } from "../install/install-prompt";
import { OnboardingSheet } from "../onboarding/onboarding-sheet";
import { useNowPlaying } from "../player/playback-provider";
import { TuningInScreen } from "../tune/tuning-in";
import { useTuneStart } from "../tune/use-tune-start";
import { ProgrammeSheet, type ProgrammePreview } from "./programme-sheet";

type Pick = {
  key: string;
  id: string;
  /** Known station (featured cards); otherwise remembered/matched from the copy. */
  stationId?: StationId;
  /** Full programme title, shown under the cover (two lines max). */
  title: string;
  /** Short cover heading when it differs from the title (featured cards). */
  coverTitle?: string;
  minutes: number | null;
  /** One sentence for the detail sheet. */
  description?: string;
  /** Why it was recommended (detail sheet). */
  reason?: string;
  onOpen: () => void;
  busy: boolean;
};

function PickCard({ pick, onSelect }: { pick: Pick; onSelect: (pick: Pick) => void }) {
  const station = pick.stationId ? stationById(pick.stationId) : stationForProgramme(pick.id, pick.title);
  const cover = programmeCover({ id: pick.id, title: pick.coverTitle ?? pick.title, stationId: station.id });
  const meta = pickMeta(station.name, pick.minutes);
  return (
    <button
      type="button"
      className="pick"
      aria-label={`${pick.title}，${meta}`}
      onClick={() => onSelect(pick)}
      disabled={pick.busy}
    >
      <span className="pick-cover">
        <TypeCover params={cover.params} radius={0} />
      </span>
      <span className="pick-text">
        <span className="pick-title">{pick.title}</span>
        <span className="pick-meta">{pick.busy ? "正在准备…" : meta}</span>
      </span>
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
  const [rotating, setRotating] = useState(false);
  const [rotationNote, setRotationNote] = useState<string | null>(null);
  const tune = useTuneStart();

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

  /** 换一批: shown ideas are not offered again; when nothing new can be offered the shelf stays. */
  const rotateIdeas = async () => {
    if (rotating || !user || !ideas?.length) return;
    setRotating(true);
    setRotationNote(null);
    try {
      const shownIds = ideas.map((idea) => idea.id);
      const next = await api.nextRecommendations(shownIds, user.id);
      const unchanged = next.ideas.every((idea) => shownIds.includes(idea.id));
      if (!unchanged) setIdeas(next.ideas);
      if (unchanged || !next.has_more) setRotationNote("今天能换的都换过了，先挑一档听听吧");
    } catch {
      setRotationNote("暂时换不了，稍后再试");
    } finally {
      setRotating(false);
    }
  };

  const openIdea = async (idea: ProgramIdea) => {
    if (busyId || !user) return;
    setBusyId(idea.id);
    setError(null);
    try {
      const batch = await api.materializeRecommendation(idea.id, user.id);
      const proposal = batch.proposals[0];
      if (!proposal) throw new Error();
      rememberProgrammeStation(proposal.id, stationForProgramme(idea.id, idea.title).id);
      rememberCoverSource(proposal.id, idea.id);
      openPlayer(`/episode/${proposal.id}`);
    } catch {
      setError("这档节目暂时开不了，换一档试试");
      setBusyId(null);
    }
  };

  // Guests: hand-picked featured cards (generated only on click). Signed in:
  // personalised ideas, or the seeds when there are none — rendered once.
  const guest = !sessionPending && !user;
  const picks: Pick[] = useMemo(() => {
    if (sessionPending) return [];
    if (!user) {
      return FEATURED_PROGRAMMES.map((item: FeaturedProgramme) => ({
        key: "featured:" + item.id,
        id: item.id,
        stationId: item.stationId,
        title: item.prompt,
        coverTitle: item.title,
        description: item.blurb,
        minutes: item.minutes,
        busy: false,
        onOpen: () => void tune.start(stationById(item.stationId), item.prompt, featuredDurationIntent(item), item.id),
      }));
    }
    if (ideas && ideas.length) {
      return dedupeByTitle(ideas).map((idea) => ({
        key: "idea:" + idea.id,
        id: idea.id,
        title: idea.title,
        coverTitle: idea.cover_title ?? undefined,
        description: idea.description,
        reason: idea.reason,
        minutes: RECOMMENDATION_MINUTES,
        busy: busyId === idea.id,
        onOpen: () => void openIdea(idea),
      }));
    }
    return dedupeByTitle(seeds ?? []).map((seed) => ({
      key: "seed:" + seed.id,
      id: seed.id,
      title: seed.title,
      coverTitle: seed.cover_title ?? undefined,
      description: seed.short_description,
      minutes: Math.max(1, Math.round(seed.estimated_duration_seconds / 60)),
      busy: false,
      onOpen: () => {
        rememberProgrammeStation(seed.id, stationForProgramme(seed.id, seed.title).id);
        openPlayer(`/episode/${seed.id}`);
      },
    }));
  }, [busyId, ideas, router, seeds, sessionPending, tune.start, user]);

  // Tapping a card shows what the programme promises; it is made only when play is pressed.
  const [selected, setSelected] = useState<Pick | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const selectPick = (pick: Pick) => {
    setSelected(pick);
    setSheetOpen(true);
  };
  const playSelected = () => {
    if (!selected) return;
    setSheetOpen(false);
    selected.onOpen();
  };
  const preview: ProgrammePreview | null = selected
    ? {
      id: selected.id,
      stationId: selected.stationId ?? stationForProgramme(selected.id, selected.title).id,
      title: selected.title,
      coverTitle: selected.coverTitle,
      minutes: selected.minutes,
      description: selected.description,
      reason: selected.reason,
    }
    : null;

  const loading = sessionPending || (!guest && (seeds === null || ideas === null));
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
          <div className="section-head">
            <h2 id="home-picks" className="section-title">{guest ? "先听这几档" : "猜你想听"}</h2>
            {guest ? (
              <p className="section-hint">登录后，这里会换成按你口味准备的节目<Link href="/account">登录</Link></p>
            ) : null}
          </div>
          {error ? <p className="inline-note" role="alert">{error}</p> : null}
          {rotationNote ? <p className="inline-note" role="status">{rotationNote}</p> : null}
          <div className="pick-grid">
            {picks.map((pick) => <PickCard key={pick.key} pick={pick} onSelect={selectPick} />)}
            {loading && !picks.length
              ? Array.from({ length: 4 }).map((_, index) => <span key={index} className="pick-skeleton" aria-hidden="true" />)
              : null}
          </div>
          {!loading && !picks.length ? (
            <p className="inline-note">还没有可以推荐的节目。<Link href="/tune">去调一档</Link></p>
          ) : null}
          {!guest && ideas?.length ? (
            <button type="button" className="pick-refresh" onClick={() => void rotateIdeas()} disabled={rotating}>
              {rotating ? "正在换…" : "换一批"}
            </button>
          ) : null}
        </section>
      </div>
      <ProgrammeSheet
        preview={preview}
        open={sheetOpen}
        busy={Boolean(selected && picks.find((pick) => pick.key === selected.key)?.busy)}
        onClose={() => setSheetOpen(false)}
        onPlay={playSelected}
      />
      <OnboardingSheet onFinished={onOnboardingFinished} />
      <InstallPrompt />
      {tune.tuning ? (
        <TuningInScreen
          station={tune.tuning}
          steps={tune.steps}
          error={tune.error}
          retryable={tune.retryable}
          onCancel={tune.cancel}
          onRetry={tune.retry}
        />
      ) : null}
    </AppShell>
  );
}
