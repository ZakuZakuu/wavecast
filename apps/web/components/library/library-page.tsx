"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { api } from "../../lib/api";
import { openPlayer } from "../../lib/player-nav";
import { listeningStatus, progressRatio, recentEntries } from "../../lib/library-view";
import { stationForProgramme, STATIONS, type StationId } from "../../lib/stations";
import type { ProgramProposal } from "../../lib/types";
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
  /** A heart on the row, and the 整期 mark (the whole episode is generated and saved). */
  favourite: boolean;
  full: boolean;
  actions: SwipeAction[];
};

type Undo = { message: string; restore: () => void };

function ProgressRing({ ratio }: { ratio: number }) {
  return (
    <span className="ring" style={{ background: `conic-gradient(var(--ink) ${ratio * 100}%, rgba(29,29,31,.1) 0)` }} aria-hidden="true">
      <span>
        <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor"><path d="M7 4.5v15l12-7.5z" /></svg>
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
  const [favProgrammes, setFavProgrammes] = useState<Record<string, ProgramProposal>>({});
  const [undo, setUndo] = useState<Undo | null>(null);
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
    void Promise.all(wanted.map((id) => api.program(id).catch(() => null))).then((items) => {
      if (!active) return;
      setFavProgrammes((current) => ({ ...current, ...Object.fromEntries(items.filter((item): item is ProgramProposal => Boolean(item)).map((item) => [item.id, item])) }));
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
    removeRecentProgramme(seedId);
    saved.forEach((item) => removeSavedEpisode(item.episodeId));
    setUndo({
      message: `已删除「${title}」`,
      restore: () => {
        restoreRecentPrograms(recent);
        saved.forEach(restoreSavedEpisode);
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
    return {
      key: record.episodeId,
      programmeId: record.seedId,
      title: record.title,
      stationId: stationForProgramme(record.seedId, record.title).id,
      status: listeningStatus(merged, now),
      ratio: progressRatio(progress, record.durationSeconds),
      href: `/episode/materialized/${record.episodeId}`,
      favourite: favouriteSet.has(record.seedId),
      full,
      actions,
    };
  };
  const proposalRow = (programme: ProgramProposal, status: string, actions: SwipeAction[]): Row => ({
    key: programme.id,
    programmeId: programme.id,
    title: programme.title,
    stationId: stationForProgramme(programme.id, programme.title).id,
    status,
    ratio: 0,
    href: `/episode/${programme.id}`,
    favourite: favouriteSet.has(programme.id),
    full: false,
    actions,
  });
  const notStarted = (programme: ProgramProposal) =>
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
  }, [created, entries, favProgrammes, favouriteSet, library.favoriteSeedIds, mineIds, now, recentBySeed, tab]);
  const loadingMine = tab === "mine" && unfetched.length > 0;

  const visible = filter === "all" ? rows : rows.filter((row) => row.stationId === filter);

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

        {visible.length ? (
          <ul className="lib-list">
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
                      <span className="lib-status">
                        <span className="filter-dot" style={{ background: STATIONS.find((s) => s.id === row.stationId)?.light }} />
                        {row.status}
                        {row.full ? <span className="lib-full">整期</span> : null}
                      </span>
                    </span>
                  </Link>
                  <button
                    type="button"
                    className="ring-button"
                    aria-label={`播放 ${row.title}`}
                    onClick={() => openPlayer(row.href)}
                  >
                    <ProgressRing ratio={row.ratio} />
                  </button>
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
    </AppShell>
  );
}
