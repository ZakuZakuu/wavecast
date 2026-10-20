"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { api, ApiRequestError } from "../../lib/api";
import { authClient } from "../../lib/auth-client";
import { programmeCover, rememberCoverSource } from "../../lib/cover/programme-cover";
import { listeningStatus, isFinished } from "../../lib/library-view";
import { lastTabPathOr } from "../../lib/nav-memory";
import { openPlayer } from "../../lib/player-nav";
import { formatFreq, rememberProgrammeStation, stationById, stationForProgramme } from "../../lib/stations";
import type { PublicProgramme } from "../../lib/types";
import { emptyUserLibrary, readUserLibrary, subscribeUserLibrary, type RecentProgramRecord } from "../../lib/user-library";
import { formatClock } from "../../lib/now-playing";
import { ChevronLeftIcon, HeartIcon, ShareIcon } from "../icons";
import { TypeCover } from "../cover/type-cover";
import { useNowPlaying } from "../player/playback-provider";
import { useFavourite } from "../../lib/use-favourite";
import { ShareSheet } from "./share-sheet";

const PROGRESS_PREFIX = "wavecast-program-progress:";

/** The player's own checkpoint is fresher than the library record. */
function storedPosition(episodeId: string): number | null {
  try {
    const raw = window.localStorage.getItem(PROGRESS_PREFIX + episodeId);
    if (!raw) return null;
    const value = Number(raw);
    if (Number.isFinite(value)) return value;
    const parsed = JSON.parse(raw) as { positionSeconds?: number };
    return typeof parsed.positionSeconds === "number" ? parsed.positionSeconds : null;
  } catch {
    return null;
  }
}

/** Why a link does not open: nothing is there, the author stopped sharing it, or it is an old one that made a copy per visitor. */
export type GoneKind = "missing" | "revoked" | "legacy";

type LoadState = { kind: "loading" } | { kind: "ready"; programme: PublicProgramme } | { kind: "missing"; why: GoneKind };

/** Forget how far an episode was heard, here and on the server, so it plays from the top. */
function restartEpisode(episodeId: string): void {
  try {
    window.localStorage.setItem(
      PROGRESS_PREFIX + episodeId,
      JSON.stringify({ positionSeconds: 0, updatedAtMs: Date.now(), continueWhileHidden: false }),
    );
  } catch {
    // The checkpoint is a convenience; the server copy below still resets.
  }
  void api.programCheckpoint(episodeId, 0).catch(() => undefined);
}

/** The radio outline, in ink: orange is reserved for what is live. */
function RadioGlyph({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" aria-hidden="true">
      <rect x="2.5" y="8" width="19" height="9" rx="4.5" />
      <path d="M6.5 12.5h.01M9.5 12.5h.01M17.5 12.5h.01" />
      <path d="M13.5 5.5v13" />
    </svg>
  );
}

function PlayGlyph() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M7.5 5.2v13.6a.9.9 0 0 0 1.4.8l10.2-6.8a.9.9 0 0 0 0-1.5L8.9 4.4a.9.9 0 0 0-1.4.8z" />
    </svg>
  );
}

const GONE_COPY: Record<GoneKind, { title: string; body: string }> = {
  missing: {
    title: "这档节目找不到了",
    body: "链接可能不完整，或者这档节目已经被删除。可以去首页挑一档，或者自己调一个。",
  },
  revoked: {
    title: "这档节目不再分享了",
    body: "作者已经撤回了分享。可以去首页挑一档，或者自己调一个。",
  },
  legacy: {
    title: "这个链接已经失效了",
    body: "以前的分享链接，打开后是各自重新生成一份。现在分享的是做好的节目本身，请让对方重新发一个新链接。",
  },
};

export function NotFound({ kind = "missing" }: { kind?: GoneKind }) {
  const copy = GONE_COPY[kind];
  return (
    <div className="pd pd-missing">
      <span className="glow" aria-hidden="true" style={{ left: -100, top: -160, width: 420, height: 340, background: "#8E8E93", opacity: 0.16 }} />
      <header className="pd-head">
        <Link href="/" className="pd-brand" aria-label="WaveCast 首页"><RadioGlyph size={26} />WaveCast</Link>
      </header>
      <main className="pd-missing-body">
        <span className="pd-missing-mark" aria-hidden="true"><RadioGlyph size={44} /></span>
        <h1>{copy.title}</h1>
        <p>{copy.body}</p>
      </main>
      <div className="pd-bar">
        <Link href="/" className="pill-button pd-primary">去首页看看</Link>
        <Link href="/tune" className="pill-button pd-secondary">调一个自己的</Link>
      </div>
    </div>
  );
}

/**
 * 节目详情: what a programme promises, and the one button that fits where the listener is in
 * it. Reached from the library, the player's 更多 menu and share links.
 */
export function ProgrammeDetailPage({ programmeId }: { programmeId: string }) {
  const router = useRouter();
  const search = useSearchParams();
  const np = useNowPlaying();
  const { data: session, isPending: sessionPending } = authClient.useSession();
  const signedIn = Boolean(session?.user);
  const [load, setLoad] = useState<LoadState>({ kind: "loading" });
  const [library, setLibrary] = useState(emptyUserLibrary);
  const [now, setNow] = useState(() => Date.now());
  const [shareOpen, setShareOpen] = useState(false);
  const { favourite, toggle: toggleFavourite } = useFavourite(programmeId);
  const [phase, setPhase] = useState<"idle" | "preparing" | "error">("idle");
  const [message, setMessage] = useState<string | null>(null);
  // Someone who arrived from inside the app (the 大家都在听 shelf, the library) can go back; someone who
  // opened a shared link has nowhere to go back to, so they get the WaveCast home link instead.
  const [cameFromApp, setCameFromApp] = useState(false);
  useEffect(() => setCameFromApp(window.history.length > 1), []);

  const coverFromLink = search.get("c");
  useEffect(() => {
    if (coverFromLink) rememberCoverSource(programmeId, coverFromLink);
  }, [coverFromLink, programmeId]);

  useEffect(() => {
    const refresh = () => {
      setLibrary(readUserLibrary());
      setNow(Date.now());
    };
    refresh();
    return subscribeUserLibrary(refresh);
  }, []);

  useEffect(() => {
    if (sessionPending) return;
    let active = true;
    setLoad({ kind: "loading" });
    api.publicProgramme(programmeId)
      .then((programme) => {
        if (!active) return;
        if (programme.station) rememberProgrammeStation(programmeId, programme.station);
        setLoad({ kind: "ready", programme });
      })
      .catch((error: unknown) => {
        if (!active) return;
        const gone = error instanceof ApiRequestError && error.status === 410;
        setLoad({ kind: "missing", why: gone ? (error.message === "revoked" ? "revoked" : "legacy") : "missing" });
      });
    return () => {
      active = false;
    };
  }, [programmeId, sessionPending, signedIn]);

  const programme = load.kind === "ready" ? load.programme : null;
  const station = programme
    ? (programme.station ? stationById(programme.station) : stationForProgramme(programme.id, programme.title, programme.description))
    : stationById("casual");
  const cover = useMemo(
    () => programme ? programmeCover({ id: programme.id, title: programme.title, stationId: station.id, coverTitle: programme.cover_title }) : null,
    [programme, station.id],
  );

  // Where this listener is in the programme: playing now, heard before, or not yet. A listener's
  // copy of a published programme is filed under the published programme's id, the one in the link.
  const mineId = programmeId;
  const record: RecentProgramRecord | undefined = library.recentPrograms
    .filter((item) => item.seedId === mineId)
    .sort((left, right) => right.updatedAt - left.updatedAt)[0];
  const playingNow = Boolean(np?.localEpisode && np.localEpisode.seed_id === mineId);
  const progress = record ? Math.max(storedPosition(record.episodeId) ?? record.progressSeconds, 0) : 0;
  const heard = record ? { ...record, progressSeconds: progress } : null;
  const finished = heard ? isFinished(heard.progressSeconds, heard.durationSeconds) : false;
  const started = heard ? heard.progressSeconds >= 1 : false;

  if (load.kind === "missing") return <NotFound kind={load.why} />;
  if (!programme || !cover) {
    return (
      <div className="pd" aria-busy="true">
        <header className="pd-head"><span className="pd-icon-slot" /></header>
        <main className="pd-main">
          <span className="pd-cover pd-skeleton" aria-hidden="true" />
        </main>
      </div>
    );
  }

  const visitor = !programme.is_owner;
  const published = Boolean(programme.published);
  const revoked = Boolean(programme.revoked);
  const minutes = Math.max(1, Math.round(programme.estimated_duration_seconds / 60));

  let primary = "播放";
  let note = "";
  if (playingNow) {
    primary = "回到播放页";
    note = "这档节目正在播放。";
  } else if (heard && finished) {
    primary = "再听一次";
    note = `${listeningStatus(heard, now)}。`;
  } else if (heard && started) {
    primary = "继续播放";
    note = `上次听到 ${formatClock(heard.progressSeconds)}，全长约 ${minutes} 分钟。`;
  }
  if (!playingNow && !heard && published) note = "这是一档做好的完整节目，点播放就能听。";
  if (revoked) note = heard ? "作者撤回了分享，你已加进节目库的这一份还能继续听。" : note;
  if (phase === "preparing") note = "正在开播…";
  if (phase === "error") note = message ?? "开播失败了，可以再试一次";

  const play = async () => {
    if (phase === "preparing") return;
    setMessage(null);
    if (playingNow) {
      openPlayer(`/episode/${encodeURIComponent(mineId)}`);
      return;
    }
    if (heard && (started || finished)) {
      // 再听一次 starts over; 继续播放 picks up the stored checkpoint.
      if (finished) restartEpisode(heard.episodeId);
      if (published) void api.recordPublishedListen(programmeId);
      openPlayer(`/episode/materialized/${encodeURIComponent(heard.episodeId)}`);
      return;
    }
    setPhase("preparing");
    try {
      if (published) {
        // A published programme is played as it is: the listener gets their own copy of it (their own
        // progress), and nothing is generated for them.
        const copy = await api.copyPublished(programmeId);
        void api.recordPublishedListen(programmeId);
        setPhase("idle");
        openPlayer(`/episode/materialized/${encodeURIComponent(copy.id)}`);
        return;
      }
      openPlayer(`/episode/${encodeURIComponent(programmeId)}`);
      setPhase("idle");
    } catch (error) {
      if (error instanceof ApiRequestError && error.status === 410) {
        setLoad({ kind: "missing", why: "revoked" });
        return;
      }
      setMessage(null);
      setPhase("error");
    }
  };

  const back = () => {
    if (window.history.length > 1) router.back();
    else router.push(lastTabPathOr("/"));
  };

  return (
    <div className="pd">
      <span className="glow" aria-hidden="true" style={{ left: -100, top: -160, width: 420, height: 340, background: station.light, opacity: 0.2 }} />
      <header className="pd-head">
        {visitor && !cameFromApp ? (
          <Link href="/" className="pd-brand" aria-label="WaveCast 首页"><RadioGlyph size={26} />WaveCast</Link>
        ) : (
          <button type="button" className="pd-icon" aria-label="返回" onClick={back}><ChevronLeftIcon size={24} strokeWidth={1.8} /></button>
        )}
        <div className="pd-head-actions">
          <button type="button" className="pd-icon" aria-label={favourite ? "取消收藏" : "收藏"} aria-pressed={favourite} onClick={toggleFavourite}>
            <HeartIcon size={22} strokeWidth={1.8} filled={favourite} />
          </button>
          {revoked ? null : (
            <button type="button" className="pd-icon" aria-label="分享这档节目" onClick={() => setShareOpen(true)}>
              <ShareIcon size={22} strokeWidth={1.8} />
            </button>
          )}
          {visitor && !signedIn ? <Link href="/account" className="pd-login">登录</Link> : null}
        </div>
      </header>

      <main className="pd-main">
        <section className="pd-hero" aria-label="节目">
          <span className="pd-cover"><TypeCover params={cover.params} radius={0} /></span>
          <span className="pd-meta">
            <span className="pd-dot" aria-hidden="true" style={{ background: station.light }} />
            FM {formatFreq(station.freq)} {station.name}
            <span aria-hidden="true">·</span>
            约 {minutes} 分钟
          </span>
          <h1 className="pd-title">{programme.title}</h1>
          {revoked ? <span className="pd-chip">作者已撤回分享</span> : null}
        </section>

        <p className="pd-description">{programme.description}</p>

        {programme.route.length ? (
          <section className="pd-route" aria-labelledby="pd-route-title">
            <h2 id="pd-route-title" className="section-title">路线</h2>
            <ol>
              {programme.route.map((beat, index) => (
                <li key={index}>
                  <span className="pd-step" aria-hidden="true">{index + 1}</span>
                  <span>{beat}</span>
                </li>
              ))}
            </ol>
            <p className="pd-route-note">
              从 {programme.opening_track_artist}《{programme.opening_track_title}》开始。后面的曲目会边听边排，可能会微调。
            </p>
          </section>
        ) : null}

        {programme.tags.length ? (
          <ul className="pd-tags">
            {programme.tags.map((tag) => <li key={tag}>{tag}</li>)}
          </ul>
        ) : null}
      </main>

      <div className="pd-bar">
        <button
          type="button"
          className="pill-button pd-primary"
          onClick={() => void play()}
          disabled={phase === "preparing"}
          aria-busy={phase === "preparing"}
        >
          {phase === "preparing" ? "正在准备…" : (
            <>
              <PlayGlyph />
              {phase === "error" ? "重试" : primary}
            </>
          )}
        </button>
        <p className={phase === "error" ? "pd-note is-error" : "pd-note"} role="status">{note}</p>
      </div>

      <ShareSheet
        open={shareOpen}
        onClose={() => setShareOpen(false)}
        target={{ id: programme.id, title: programme.title, coverTitle: programme.cover_title, stationId: station.id, episodeId: record?.episodeId ?? null }}
      />
    </div>
  );
}
