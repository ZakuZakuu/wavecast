"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState, type CSSProperties } from "react";

import { api } from "../../lib/api";
import { openPlayer } from "../../lib/player-nav";
import { authClient } from "../../lib/auth-client";
import { programmeCover, rememberCoverSource } from "../../lib/cover/programme-cover";
import { dedupeByTitle, featureEyebrow, ideaStation, pickMeta, RECOMMENDATION_MINUTES } from "../../lib/home-picks";
import { FEATURED_PROGRAMMES, featuredDurationIntent, type FeaturedProgramme } from "../../lib/featured";
import { clearHomeCache, LAST_USER_KEY, readHomeCache, sharedRequest, writeHomeCache } from "../../lib/home-cache";
import { requestLoginHint } from "../../lib/login-nudge";
import { usePublicShelf } from "../../lib/public-shelf";
import {
  rememberProgrammeStation,
  stationById,
  stationForProgramme,
  STATIONS,
  type StationId,
} from "../../lib/stations";
import type { ProgramIdea, Seed } from "../../lib/types";
import { recordCreatedProgram } from "../../lib/user-library";
import { AppShell } from "../app-shell";
import { Guide } from "../guide/guide";
import { TypeCover } from "../cover/type-cover";
import { InstallPrompt } from "../install/install-prompt";
import { OnboardingSheet } from "../onboarding/onboarding-sheet";
import { useNowPlaying } from "../player/playback-provider";
import { TuningInScreen } from "../tune/tuning-in";
import { useTuneStart } from "../tune/use-tune-start";
import { ProgrammeSheet, type ProgrammePreview } from "./programme-sheet";
import { PublicShelf } from "./public-shelf";
import { PullToRefresh } from "./pull-to-refresh";
import { StationTile } from "./station-tile";

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

/** What a card shows: its station, its cover and the line under the title. */
function usePickView(pick: Pick) {
  const station = pick.stationId ? stationById(pick.stationId) : stationForProgramme(pick.id, pick.title);
  const cover = programmeCover({ id: pick.id, title: pick.coverTitle ?? pick.title, stationId: station.id });
  return { station, cover, meta: pickMeta(station.name, pick.minutes) };
}

function PickCard({ pick, onSelect }: { pick: Pick; onSelect: (pick: Pick) => void }) {
  const { cover, meta } = usePickView(pick);
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

/** The first pick, larger: the station's own pale colour behind a bigger cover, and what it is about. */
function FeatureCard({ pick, onSelect }: { pick: Pick; onSelect: (pick: Pick) => void }) {
  const { station, cover, meta } = usePickView(pick);
  return (
    <button
      type="button"
      className="pick-feature"
      data-guide="home-feature"
      style={{ "--tile-light": station.light, "--tile-deep": station.deep } as CSSProperties}
      aria-label={`${pick.title}，${meta}`}
      onClick={() => onSelect(pick)}
      disabled={pick.busy}
    >
      <span className="pick-feature-cover">
        <TypeCover params={cover.params} radius={0} />
      </span>
      <span className="pick-feature-text">
        <span className="pick-feature-eyebrow">{pick.busy ? "正在准备…" : featureEyebrow(station.name, pick.minutes)}</span>
        <span className="pick-feature-title">{pick.title}</span>
        {pick.description ? <span className="pick-feature-blurb">{pick.description}</span> : null}
      </span>
    </button>
  );
}

export function HomePage({ onOnboardingFinished }: { onOnboardingFinished?: () => void } = {}) {
  const router = useRouter();
  const np = useNowPlaying();
  const { data: session, isPending: sessionPending } = authClient.useSession();
  const user = session?.user ?? null;
  // Cards from the last visit are shown at once; the fresh answer quietly replaces them.
  const [seeds, setSeeds] = useState<Seed[] | null>(null);
  const [ideas, setIdeas] = useState<ProgramIdea[] | null>(null);
  const [lastUserId, setLastUserId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [rotating, setRotating] = useState(false);
  const [rotationNote, setRotationNote] = useState<string | null>(null);
  const tune = useTuneStart();
  // While the session is still being checked, the person who was signed in last is assumed.
  const userId = user?.id ?? (sessionPending ? lastUserId : null);
  const shelf = usePublicShelf(userId, userId !== null || !sessionPending);
  const askToSignIn = () => requestLoginHint({ title: "登录后才能换一批", note: "登录后可以获得完整推荐" });

  useEffect(() => {
    setSeeds(readHomeCache<Seed[]>("seeds"));
    setLastUserId(readHomeCache<string>(LAST_USER_KEY));
    let active = true;
    sharedRequest("seeds", () => api.seeds())
      .then((value) => {
        if (!active) return;
        writeHomeCache("seeds", value);
        setSeeds(value);
      })
      .catch(() => {
        // Keep what was shown; only an empty first visit has nothing to fall back on.
        if (active) setSeeds((current) => current ?? []);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (sessionPending) return;
    if (!user) {
      clearHomeCache(LAST_USER_KEY);
      setLastUserId(null);
      setIdeas(null);
      return;
    }
    writeHomeCache(LAST_USER_KEY, user.id);
    setLastUserId(user.id);
    const key = "ideas:" + user.id;
    const cached = readHomeCache<ProgramIdea[]>(key);
    if (cached) setIdeas(cached);
    let active = true;
    sharedRequest(key, () => api.recommendations(user.id))
      .then((value) => {
        if (!active) return;
        writeHomeCache(key, value);
        setIdeas(value);
      })
      .catch(() => {
        if (active) setIdeas((current) => current ?? []);
      });
    return () => {
      active = false;
    };
  }, [sessionPending, user?.id]);

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
      rememberProgrammeStation(
        proposal.id,
        ideaStation(idea) ?? stationForProgramme(idea.id, idea.title).id,
      );
      rememberCoverSource(proposal.id, idea.id);
      recordCreatedProgram(proposal.id);
      openPlayer(`/episode/${proposal.id}`);
    } catch {
      setError("这档节目暂时开不了，换一档试试");
      setBusyId(null);
    }
  };

  // Guests: hand-picked featured cards (generated only on click). Signed in:
  // personalised ideas, or the seeds when there are none — rendered once.
  const guest = !sessionPending && !user;
  // A session still being checked keeps showing the last visit's cards instead of emptying the page.
  const cardsKnown = sessionPending && lastUserId !== null && (ideas !== null || seeds !== null);
  const picks: Pick[] = useMemo(() => {
    if (sessionPending && !cardsKnown) return [];
    if (!user && !cardsKnown) {
      return FEATURED_PROGRAMMES.map((item: FeaturedProgramme) => ({
        key: "featured:" + item.id,
        id: item.id,
        stationId: item.stationId,
        title: item.displayTitle,
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
        stationId: ideaStation(idea),
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
  }, [busyId, cardsKnown, ideas, router, seeds, sessionPending, tune.start, user]);

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

  const [feature, ...rail] = picks;
  // The taste sheet (signed-in people, once) comes before the guide; guests have none.
  const [tasteSettled, setTasteSettled] = useState(false);
  const tasteDone = useCallback(() => {
    setTasteSettled(true);
    onOnboardingFinished?.();
  }, [onOnboardingFinished]);

  const loading = (sessionPending && !cardsKnown) || (!guest && !cardsKnown && (seeds === null || ideas === null));
  const glow = np?.station?.light ?? "#5C7CE0";
  const initial = user?.name?.trim().slice(0, 1) || user?.email?.slice(0, 1)?.toUpperCase() || null;

  return (
    <AppShell
      background={<span className="glow" aria-hidden="true" style={{ left: -100, top: -160, width: 420, height: 340, background: glow, opacity: 0.14 }} />}
    >
      <PullToRefresh canRefresh={Boolean(user)} onRefresh={rotateIdeas} onBlocked={askToSignIn}>
        <div className="home">
          <header className="home-head">
            <h1 className="page-title">首页</h1>
            <Link href="/account" className="avatar" aria-label="账户">
              {initial ?? (
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true"><circle cx="12" cy="9" r="3.6" /><path d="M5.5 19.5a6.5 6.5 0 0 1 13 0" /></svg>
              )}
            </Link>
          </header>

          <section className="home-section" aria-labelledby="home-picks">
            <div className="section-head" data-guide="home-picks-head">
              <div className="section-title-row">
                <h2 id="home-picks" className="section-title">{guest ? "先听这几档" : "猜你想听"}</h2>
                {guest || ideas?.length ? (
                  <button type="button" className="pick-refresh" onClick={guest ? askToSignIn : () => void rotateIdeas()} disabled={rotating}>
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><polyline points="23 4 23 10 17 10" /><polyline points="1 20 1 14 7 14" /><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" /></svg>
                    {rotating ? "正在换…" : "换一批"}
                  </button>
                ) : null}
              </div>
              {guest ? (
                <p className="section-hint">登录后，这里会换成按你口味准备的节目<Link href="/account">登录</Link></p>
              ) : null}
            </div>
            {error ? <p className="inline-note" role="alert">{error}</p> : null}
            {rotationNote ? <p className="inline-note" role="status">{rotationNote}</p> : null}
            {feature ? <FeatureCard pick={feature} onSelect={selectPick} /> : null}
            {loading && !picks.length ? <span className="pick-feature-skeleton" aria-hidden="true" /> : null}
            {rail.length || (loading && !picks.length) ? (
              <div className="pick-rail">
                {rail.map((pick) => <PickCard key={pick.key} pick={pick} onSelect={selectPick} />)}
                {loading && !picks.length
                  ? Array.from({ length: 3 }).map((_, index) => <span key={index} className="pick-skeleton" aria-hidden="true" />)
                  : null}
              </div>
            ) : null}
            {!loading && !picks.length ? (
              <p className="inline-note">还没有可以推荐的节目。<Link href="/tune">去调一档</Link></p>
            ) : null}
          </section>
          <PublicShelf shelf={shelf} />
          <section className="home-section home-stations" aria-labelledby="home-stations">
            <h2 id="home-stations" className="section-title">电台</h2>
            <div className="station-row" data-guide="home-stations">
              {STATIONS.map((station) => <StationTile key={station.id} station={station} />)}
            </div>
          </section>

        </div>
      </PullToRefresh>
      <ProgrammeSheet
        preview={preview}
        open={sheetOpen}
        busy={Boolean(selected && picks.find((pick) => pick.key === selected.key)?.busy)}
        onClose={() => setSheetOpen(false)}
        onPlay={playSelected}
      />
      <OnboardingSheet onFinished={tasteDone} />
      <Guide trigger="home" ready={guest || tasteSettled} />
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
