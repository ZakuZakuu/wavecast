"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { api, ApiRequestError } from "../../lib/api";
import { useCreatingFullVersions } from "../../lib/full-version-requests";
import { clearUnseenFullVersions, FULL_VERSION_POLL_MS, watchFullVersion } from "../../lib/full-versions";
import { isBeingMade } from "../../lib/publications";
import { openPlayer } from "../../lib/player-nav";
import { listeningStatus, progressRatio, recentEntries } from "../../lib/library-view";
import { stationForProgramme, STATIONS, type StationId } from "../../lib/stations";
import type { FullVersionItem, ProgramProposal, PublicationItem } from "../../lib/types";
import {
  emptyUserLibrary,
  isFavoriteSeed,
  readUserLibrary,
  removeRecentProgramme,
  removeSavedEpisode,
  restoreRecentPrograms,
  restoreSavedEpisode,
  subscribeUserLibrary,
  toggleFavoriteSeed,
  type RecentProgramRecord,
  type SavedEpisodeRecord,
  type UserLibraryState,
} from "../../lib/user-library";
import { AppShell } from "../app-shell";
import { Guide } from "../guide/guide";
import { HeartIcon } from "../icons";
import { Segmented } from "../segmented";
import { ProgrammeCoverView } from "../cover/programme-cover-view";
import { SwipeRow, type SwipeAction } from "./swipe-row";

const TABS = [
  { id: "recent", label: "最近" },
  { id: "fav", label: "收藏" },
  { id: "mine", label: "我调的" },
] as const;
type TabId = typeof TABS[number]["id"];

const PROGRESS_PREFIX = "wavecast-program-progress:";
/** How long 撤销 stays on screen after a delete or an un-favourite. */
export const UNDO_MS = 5000;

/** The player's own listener checkpoint is fresher than the library record. */
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

type Row = {
  key: string;
  programmeId: string;
  title: string;
  stationId: StationId;
  status: string;
  ratio: number;
  href: string;
  /** A heart on the row. */
  favourite: boolean;
  /**
   * The one mark after the status: shared (a published programme is a 完整版 by definition), else
   * 完整版 for one that has been listened to; a new one says "已准备好" and needs none.
   */
  marker: "shared" | "full" | null;
  /** Plays the row when it has no episode to open (a favourited published programme not yet played). */
  play?: () => void;
  actions: SwipeAction[];
  /** The 完整版 of the row's episode: being prepared (with how far), failed (with a way to retry), or not asked for. */
  fullState: FullVersionItem["status"];
  prep: number;
  retry?: () => void;
};

type Undo = { message: string; restore: () => void };

// What the server last said about the listed episodes. Kept for the life of the page, so coming back to
// 节目库 draws the marks at once instead of drawing a wrong one first and correcting it a moment later.
const lastKnown: {
  full: Record<string, FullVersionItem>;
  publications: Record<string, PublicationItem>;
  publicationsAsked: boolean;
} = { full: {}, publications: {}, publicationsAsked: false };

/** For tests: forget what the server last said. */
export function resetLibraryKnowledge(): void {
  lastKnown.full = {};
  lastKnown.publications = {};
  lastKnown.publicationsAsked = false;
}

/** What a row needs of a programme that has no listening record. */
type ProgrammeSummary = Pick<ProgramProposal, "id" | "title" | "estimated_duration_seconds">;

/** A programme the listener has not played: a proposal of their own, or a published one. */
function programmeSummary(id: string): Promise<ProgrammeSummary | null> {
  if (id.startsWith("pub-")) {
    return api.publicProgramme(id)
      .then((programme) => ({ id: programme.id, title: programme.title, estimated_duration_seconds: programme.estimated_duration_seconds }))
      .catch(() => null);
  }
  return api.program(id).catch(() => null);
}

function ProgressRing({ ratio }: { ratio: number }) {
  return (
    <span className="ring" style={{ background: `conic-gradient(var(--ink) ${ratio * 100}%, rgba(29,29,31,.1) 0)` }} aria-hidden="true">
      <span>
        <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor"><path d="M7 4.5v15l12-7.5z" /></svg>
      </span>
    </span>
  );
}

/** What a row is besides its status: shared with others, or a 完整版. Never both: shared says it all. */
function RowMarker({ kind, guide }: { kind: "shared" | "full"; guide: boolean }) {
  return kind === "shared" ? (
    <svg className="lib-marker" data-guide={guide ? "lib-marker" : undefined} width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" role="img" aria-label="已分享">
      <path d="M12 15.5V4m0 0L8 8m4-4 4 4" />
      <path d="M6 11.5H5.5a1.5 1.5 0 0 0-1.5 1.5v5.5a1.5 1.5 0 0 0 1.5 1.5h13a1.5 1.5 0 0 0 1.5-1.5V13a1.5 1.5 0 0 0-1.5-1.5H18" />
    </svg>
  ) : (
    <svg className="lib-marker" data-guide={guide ? "lib-marker" : undefined} width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" role="img" aria-label="完整版">
      <circle cx="12" cy="12" r="9" />
      <path d="m8 12.3 2.8 2.8L16.2 9.4" />
    </svg>
  );
}

/** 完整版 being prepared: an orange ring filling up, with the arrow of the download in it. */
function PrepRing({ percent }: { percent: number }) {
  return (
    <span className="ring" style={{ background: `conic-gradient(var(--live) ${percent}%, rgba(29,29,31,.1) 0)` }} role="img" aria-label={`准备中 ${percent}%`}>
      <span>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 4v11m0 0-4.5-4.5M12 15l4.5-4.5M5 20h14" /></svg>
      </span>
    </span>
  );
}

export function LibraryPage() {
  const [tab, setTab] = useState<TabId>("recent");
  const [filter, setFilter] = useState<StationId | "all">("all");
  const [library, setLibrary] = useState<UserLibraryState>(emptyUserLibrary);
  // Programmes of 我调的 with no listening record, as the server describes them (null: it would not).
  const [created, setCreated] = useState<Record<string, ProgramProposal | null>>({});
  // Favourites with no recent or saved record (hearted from a detail page): their programme, once fetched.
  const [favProgrammes, setFavProgrammes] = useState<Record<string, ProgrammeSummary>>({});
  const [undo, setUndo] = useState<Undo | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [fullStates, setFullStates] = useState<Record<string, FullVersionItem>>(lastKnown.full);
  // The publication of each listed episode that is the listener's own and has one.
  const [publications, setPublications] = useState<Record<string, PublicationItem>>(lastKnown.publications);
  // Until it is known which are shared, a 完整版 mark could be wrong (a shared one shows the share mark).
  const [publicationsKnown, setPublicationsKnown] = useState(lastKnown.publicationsAsked);
  const [now, setNow] = useState(() => Date.now());
  // Only one row may show its delete button; any tap outside it closes it.
  const [openKey, setOpenKey] = useState<string | null>(null);
  useEffect(() => {
    if (!openKey) return;
    const onDown = (event: PointerEvent) => {
      const row = (event.target as Element | null)?.closest?.("[data-row-key]");
      if (row?.getAttribute("data-row-key") !== openKey) setOpenKey(null);
    };
    document.addEventListener("pointerdown", onDown, true);
    return () => document.removeEventListener("pointerdown", onDown, true);
  }, [openKey]);

  useEffect(() => {
    const refresh = () => {
      setLibrary(readUserLibrary());
      setNow(Date.now());
    };
    refresh();
    return subscribeUserLibrary(refresh);
  }, []);

  const entries = useMemo(
    () => recentEntries(library.recentPrograms, library.savedEpisodes),
    [library.recentPrograms, library.savedEpisodes],
  );
  const recentBySeed = useMemo(() => new Map(entries.map((entry) => [entry.record.seedId, entry])), [entries]);
  // Opening 节目库 is how the listener "sees" what finished in the background.
  useEffect(() => clearUnseenFullVersions(), []);

  // Where each listed episode's 完整版 stands, asked again every few seconds while one is being prepared.
  const episodeKey = entries.slice(0, 30).map(({ record }) => record.episodeId).join(",");
  const anyPreparing = Object.values(fullStates).some((item) => item.status === "preparing")
    || Object.values(publications).some((item) => isBeingMade(item));
  useEffect(() => {
    if (!episodeKey) return;
    let active = true;
    const load = () => {
      const ids = episodeKey.split(",");
      void api.fullVersionStatuses(ids)
        .then((items) => {
          lastKnown.full = Object.fromEntries(items.map((item) => [item.episode_id, item]));
          if (active) setFullStates(lastKnown.full);
        })
        .catch(() => undefined);
      void api.publicationStatuses(ids)
        .then((items) => {
          lastKnown.publications = Object.fromEntries(items.map((item) => [item.episode_id, item]));
          lastKnown.publicationsAsked = true;
          if (active) {
            setPublications(lastKnown.publications);
            setPublicationsKnown(true);
          }
        })
        .catch(() => undefined);
    };
    load();
    if (!anyPreparing) return () => { active = false; };
    const timer = window.setInterval(load, FULL_VERSION_POLL_MS);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [anyPreparing, episodeKey]);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 3200);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const retryFull = (episodeId: string, programmeId: string, title: string) => {
    api.materialize(episodeId)
      .then(() => {
        watchFullVersion({ episodeId, programmeId, title });
        setFullStates((current) => ({ ...current, [episodeId]: { episode_id: episodeId, programme_id: programmeId, status: "preparing", progress: 0 } }));
        setNotice("重新准备");
      })
      .catch((reason: unknown) => {
        setNotice(reason instanceof ApiRequestError && reason.status === 429 ? "最多同时准备 2 档" : "没有准备成功，可以再试一次");
      });
  };

  // A programme the listener has a record of needs no request; only the rest are asked for.
  const mineIds = useMemo(() => library.createdProgramIds.slice(0, 30), [library.createdProgramIds]);
  const unfetched = mineIds.filter((id) => !recentBySeed.has(id) && !(id in created));
  const unfetchedKey = unfetched.join(",");
  useEffect(() => {
    if (tab !== "mine" || !unfetchedKey) return;
    let active = true;
    const ids = unfetchedKey.split(",");
    void Promise.all(ids.map((id) => api.program(id).catch(() => null))).then((items) => {
      if (active) setCreated((current) => ({ ...current, ...Object.fromEntries(ids.map((id, index) => [id, items[index]])) }));
    });
    return () => {
      active = false;
    };
  }, [tab, unfetchedKey]);

  useEffect(() => {
    if (!undo) return;
    const timer = window.setTimeout(() => setUndo(null), UNDO_MS);
    return () => window.clearTimeout(timer);
  }, [undo]);

  const favouriteSet = useMemo(() => new Set(library.favoriteSeedIds), [library.favoriteSeedIds]);
  const missingFavourites = useMemo(() => {
    const known = new Set(entries.map(({ record }) => record.seedId));
    return library.favoriteSeedIds.filter((id) => !known.has(id));
  }, [entries, library.favoriteSeedIds]);
  useEffect(() => {
    if (tab !== "fav") return;
    const wanted = missingFavourites.filter((id) => !favProgrammes[id]).slice(0, 30);
    if (!wanted.length) return;
    let active = true;
    void Promise.all(wanted.map((id) => programmeSummary(id))).then((items) => {
      if (!active) return;
      setFavProgrammes((current) => ({ ...current, ...Object.fromEntries(items.filter((item): item is ProgrammeSummary => Boolean(item)).map((item) => [item.id, item])) }));
    });
    return () => {
      active = false;
    };
  }, [favProgrammes, missingFavourites, tab]);

  /** Takes a programme out of the list; 撤销 puts back what was taken (recent and saved records). */
  const deleteProgramme = (seedId: string, title: string) => {
    const current = readUserLibrary();
    const recent = current.recentPrograms.filter((item) => item.seedId === seedId);
    const saved = current.savedEpisodes.filter((item) => item.seedId === seedId);
    // Deleting a programme that is shared stops sharing it; copies people already hold keep playing.
    const shared = [...recent, ...saved]
      .map((item) => publications[item.episodeId])
      .find((item): item is PublicationItem => Boolean(item) && item.status === "published");
    removeRecentProgramme(seedId);
    saved.forEach((item) => removeSavedEpisode(item.episodeId));
    if (shared) {
      void api.revokePublication(shared.id)
        .then((item) => setPublications((all) => ({ ...all, [item.episode_id]: item })))
        .catch(() => undefined);
    }
    setUndo({
      message: shared ? `已删除「${title}」，分享也撤回了` : `已删除「${title}」`,
      restore: () => {
        restoreRecentPrograms(recent);
        saved.forEach(restoreSavedEpisode);
        if (shared) {
          void api.restorePublication(shared.id)
            .then((item) => setPublications((all) => ({ ...all, [item.episode_id]: item })))
            .catch(() => undefined);
        }
      },
    });
  };
  const removeFavourite = (seedId: string, title: string) => {
    toggleFavoriteSeed(seedId);
    setUndo({
      message: `已取消收藏「${title}」`,
      restore: () => {
        if (!isFavoriteSeed(seedId)) toggleFavoriteSeed(seedId);
      },
    });
  };

  const favouriteAction = (seedId: string, title: string, favourite: boolean): SwipeAction => ({
    label: favourite ? "取消收藏" : "收藏",
    ariaLabel: `${favourite ? "取消收藏" : "收藏"} ${title}`,
    tone: "favourite",
    onPress: () => toggleFavoriteSeed(seedId),
  });
  const deleteAction = (seedId: string, title: string): SwipeAction => ({
    label: "删除",
    ariaLabel: `删除 ${title}`,
    tone: "danger",
    removes: true,
    onPress: () => deleteProgramme(seedId, title),
  });

  const recordRow = (record: RecentProgramRecord | SavedEpisodeRecord, full: boolean, actions: SwipeAction[]): Row => {
    const position = storedPosition(record.episodeId);
    const progress = position !== null ? Math.max(position, 0) : record.progressSeconds;
    const merged = { ...record, progressSeconds: progress };
    const state = fullStates[record.episodeId];
    const fullState = state?.status ?? "none";
    // Preparing and failed say so instead of the listening status; a finished one that was never played says it is ready.
    const status = fullState === "preparing"
      ? `准备中 · ${state?.progress ?? 0}%`
      : fullState === "failed"
        ? "准备失败"
        : fullState === "ready" && progress < 1
          ? `已准备好 · 约 ${Math.max(1, Math.round(record.durationSeconds / 60))} 分钟`
          : listeningStatus(merged, now);
    const shared = publications[record.episodeId]?.status === "published";
    const newlyReady = fullState === "ready" && progress < 1;
    return {
      key: record.episodeId,
      programmeId: record.seedId,
      title: record.title,
      stationId: stationForProgramme(record.seedId, record.title).id,
      status,
      ratio: progressRatio(progress, record.durationSeconds),
      href: `/episode/materialized/${record.episodeId}`,
      favourite: favouriteSet.has(record.seedId),
      marker: shared ? "shared" : publicationsKnown && (full || fullState === "ready") && !newlyReady ? "full" : null,
      actions: fullState === "failed" ? actions.filter((action) => action.tone === "danger") : actions,
      fullState,
      prep: state?.progress ?? 0,
      retry: fullState === "failed" ? () => retryFull(record.episodeId, record.seedId, record.title) : undefined,
    };
  };
  const proposalRow = (programme: ProgrammeSummary, status: string, actions: SwipeAction[]): Row => ({
    key: programme.id,
    programmeId: programme.id,
    title: programme.title,
    stationId: stationForProgramme(programme.id, programme.title).id,
    status,
    ratio: 0,
    href: `/episode/${programme.id}`,
    // A published programme is played as the listener's own copy of it, not started from a seed.
    play: programme.id.startsWith("pub-")
      ? () => void api.copyPublished(programme.id)
        .then((copy) => openPlayer(`/episode/materialized/${encodeURIComponent(copy.id)}`))
        .catch(() => setNotice("现在打不开这档节目"))
      : undefined,
    favourite: favouriteSet.has(programme.id),
    marker: null,
    actions,
    fullState: "none",
    prep: 0,
  });
  const notStarted = (programme: ProgrammeSummary) =>
    `约 ${Math.max(1, Math.round(programme.estimated_duration_seconds / 60))} 分钟，还没听`;

  const rows: Row[] = useMemo(() => {
    if (tab === "recent") {
      return entries.map(({ record, full }) =>
        recordRow(record, full, [
          favouriteAction(record.seedId, record.title, favouriteSet.has(record.seedId)),
          deleteAction(record.seedId, record.title),
        ]));
    }
    if (tab === "fav") {
      const bySeed = new Map(entries.map((entry) => [entry.record.seedId, entry]));
      return library.favoriteSeedIds.flatMap((seedId) => {
        const unfavourite: SwipeAction = {
          label: "取消收藏",
          ariaLabel: `取消收藏 ${bySeed.get(seedId)?.record.title ?? favProgrammes[seedId]?.title ?? ""}`,
          tone: "favourite",
          removes: true,
          onPress: () => removeFavourite(seedId, bySeed.get(seedId)?.record.title ?? favProgrammes[seedId]?.title ?? ""),
        };
        const entry = bySeed.get(seedId);
        if (entry) return [recordRow(entry.record, entry.full, [unfavourite])];
        const programme = favProgrammes[seedId];
        return programme ? [proposalRow(programme, notStarted(programme), [unfavourite])] : [];
      });
    }
    return mineIds.flatMap((id) => {
      const recent = recentBySeed.get(id);
      if (recent) return [recordRow(recent.record, recent.full, [])];
      const programme = created[id];
      return programme ? [proposalRow(programme, notStarted(programme), [])] : [];
    });
  }, [created, entries, favProgrammes, favouriteSet, fullStates, library.favoriteSeedIds, mineIds, now, publications, publicationsKnown, recentBySeed, tab]);
  const loadingMine = tab === "mine" && unfetched.length > 0;

  const visible = filter === "all" ? rows : rows.filter((row) => row.stationId === filter);
  // The first row with a mark carries the guide's anchor; the guide only runs once there is one to point at.
  const firstMarked = visible.find((row) => row.marker)?.key ?? null;
  // Programmes being made for a 完整版 are not in the library yet; they hold a place at the top meanwhile.
  const makingNow = useCreatingFullVersions().filter((item) => tab === "recent" && (filter === "all" || item.stationId === filter));

  return (
    <AppShell>
      <div className="library">
        <h1 className="page-title">节目库</h1>

        <Segmented
          kind="tab"
          label="节目分类"
          options={TABS.map((item) => ({ value: item.id, label: item.label }))}
          value={tab}
          onChange={setTab}
        />

        <div className="filter-row" role="group" aria-label="按电台筛选">
          <button type="button" className={filter === "all" ? "filter-chip is-on" : "filter-chip"} aria-pressed={filter === "all"} onClick={() => setFilter("all")}>
            <span className="filter-dot" style={{ background: filter === "all" ? "#FFFFFF" : "var(--ink)" }} />全部
          </button>
          {STATIONS.map((station) => (
            <button
              key={station.id}
              type="button"
              className={filter === station.id ? "filter-chip is-on" : "filter-chip"}
              aria-pressed={filter === station.id}
              onClick={() => setFilter(station.id)}
            >
              <span className="filter-dot" style={{ background: station.light }} />{station.name}
            </button>
          ))}
        </div>

        {visible.length || makingNow.length ? (
          <ul className="lib-list">
            {makingNow.map((item) => (
              <li key={item.id} className="lib-row lib-making" aria-label={`${item.title}，正在编排`}>
                <div className="lib-link">
                  <span className="lib-cover">
                    <ProgrammeCoverView id={item.id} title={item.title} stationId={item.stationId} bare radius={0} />
                  </span>
                  <span className="lib-copy">
                    <span className="lib-title-line"><span className="lib-title">{item.title}</span></span>
                    <span className="lib-status">
                      <span className="filter-dot" style={{ background: STATIONS.find((s) => s.id === item.stationId)?.light }} />
                      正在编排
                    </span>
                  </span>
                  <span className="lib-making-ring" aria-hidden="true" />
                </div>
              </li>
            ))}
            {visible.map((row) => (
              <SwipeRow
                key={row.key}
                rowKey={row.key}
                actions={row.actions}
                open={openKey === row.key}
                onOpenChange={(next) => setOpenKey(next ? row.key : null)}
              >
                <div className="lib-link">
                  <Link
                    href={`/program/${encodeURIComponent(row.programmeId)}`}
                    className="lib-main"
                    draggable={false}
                    aria-label={`${row.title}，${row.status}，节目详情`}
                  >
                    <span className="lib-cover">
                      <ProgrammeCoverView id={row.programmeId} title={row.title} stationId={row.stationId} bare radius={0} />
                    </span>
                    <span className="lib-copy">
                      <span className="lib-title-line">
                        <span className="lib-title">{row.title}</span>
                        {row.favourite ? <HeartIcon className="lib-heart" size={14} strokeWidth={2} filled aria-label="已收藏" aria-hidden={false} role="img" /> : null}
                      </span>
                      <span className={`lib-status is-${row.fullState}${row.fullState === "ready" && row.status.startsWith("已准备好") ? " is-new" : ""}`}>
                        <span className="filter-dot" style={{ background: STATIONS.find((s) => s.id === row.stationId)?.light }} />
                        {row.status}
                        {row.marker ? <RowMarker kind={row.marker} guide={row.key === firstMarked} /> : null}
                      </span>
                    </span>
                  </Link>
                  {row.retry ? (
                    <button type="button" className="lib-retry" aria-label={`重试 ${row.title}`} onClick={row.retry}>重试</button>
                  ) : (
                    <button
                      type="button"
                      className="ring-button"
                      aria-label={`播放 ${row.title}`}
                      onClick={() => (row.play ? row.play() : openPlayer(row.href))}
                    >
                      {row.fullState === "preparing" ? <PrepRing percent={row.prep} /> : <ProgressRing ratio={row.ratio} />}
                    </button>
                  )}
                  {row.fullState === "preparing" ? <span className="lib-prep-line" style={{ width: `${row.prep}%` }} aria-hidden="true" /> : null}
                </div>
              </SwipeRow>
            ))}
          </ul>
        ) : loadingMine ? (
          <div className="lib-empty"><p>正在载入…</p></div>
        ) : (
          <div className="lib-empty">
            <p>
              {tab === "recent"
                ? "听过的节目会留在这里，下次从上次的位置接着听。"
                : tab === "fav"
                  ? <>还没有收藏。在播放页或节目详情里点 ♡，<br />节目就会留在这里。</>
                  : "在调频页开播的节目会留在这里。"}
            </p>
            <Link href="/tune" className="pill-button">去调频</Link>
          </div>
        )}
      </div>
      {notice && !undo ? <div className="undo-toast" role="status"><span>{notice}</span></div> : null}
      {undo ? (
        <div className="undo-toast" role="status">
          <span>{undo.message}</span>
          <button
            type="button"
            onClick={() => {
              undo.restore();
              setUndo(null);
            }}
          >
            撤销
          </button>
        </div>
      ) : null}
      <Guide trigger="library" ready={firstMarked !== null} />
    </AppShell>
  );
}
