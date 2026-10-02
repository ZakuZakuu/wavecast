"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { api } from "../../lib/api";
import { dedupeByProgramme, listeningStatus, progressRatio } from "../../lib/library-view";
import { stationForProgramme, STATIONS, type StationId } from "../../lib/stations";
import type { ProgramProposal } from "../../lib/types";
import {
  emptyUserLibrary,
  readUserLibrary,
  removeRecentProgramme,
  removeSavedEpisode,
  subscribeUserLibrary,
  type RecentProgramRecord,
  type UserLibraryState,
} from "../../lib/user-library";
import { AppShell } from "../app-shell";
import { ProgrammeCoverView } from "../cover/programme-cover-view";
import { SwipeRow } from "./swipe-row";

const TABS = [
  { id: "recent", label: "最近" },
  { id: "saved", label: "收藏" },
  { id: "mine", label: "我调的" },
] as const;
type TabId = typeof TABS[number]["id"];

const PROGRESS_PREFIX = "wavecast-program-progress:";

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
  onDelete?: () => void;
  deleteLabel: string;
};

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
  const [created, setCreated] = useState<ProgramProposal[]>([]);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const refresh = () => {
      setLibrary(readUserLibrary());
      setNow(Date.now());
    };
    refresh();
    return subscribeUserLibrary(refresh);
  }, []);

  useEffect(() => {
    if (tab !== "mine") return;
    let active = true;
    void Promise.all(library.createdProgramIds.slice(0, 30).map((id) => api.program(id).catch(() => null)))
      .then((items) => {
        if (active) setCreated(items.filter((item): item is ProgramProposal => Boolean(item)));
      });
    return () => {
      active = false;
    };
  }, [library.createdProgramIds, tab]);

  const recordRow = (record: RecentProgramRecord, onDelete: () => void): Row => {
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
      onDelete,
      deleteLabel: `删除 ${record.title}`,
    };
  };

  const rows: Row[] = useMemo(() => {
    if (tab === "recent") {
      return dedupeByProgramme(library.recentPrograms)
        .map((record) => recordRow(record, () => removeRecentProgramme(record.seedId)));
    }
    if (tab === "saved") {
      return dedupeByProgramme(library.savedEpisodes)
        .map((record) => recordRow(record, () => removeSavedEpisode(record.episodeId)));
    }
    const recentBySeed = new Map(dedupeByProgramme(library.recentPrograms).map((record) => [record.seedId, record]));
    return created.map((programme) => {
      const recent = recentBySeed.get(programme.id);
      if (recent) return { ...recordRow(recent, () => removeRecentProgramme(recent.seedId)), onDelete: undefined };
      return {
        key: programme.id,
        programmeId: programme.id,
        title: programme.title,
        stationId: stationForProgramme(programme.id, programme.title).id,
        status: `约 ${Math.max(1, Math.round(programme.estimated_duration_seconds / 60))} 分钟，还没听`,
        ratio: 0,
        href: `/episode/${programme.id}`,
        deleteLabel: "",
      };
    });
  }, [created, library, now, tab]);

  const visible = filter === "all" ? rows : rows.filter((row) => row.stationId === filter);

  return (
    <AppShell>
      <div className="library">
        <h1 className="page-title">节目库</h1>

        <div className="segmented" role="tablist" aria-label="节目分类">
          {TABS.map((item) => (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={tab === item.id}
              className={tab === item.id ? "is-selected" : undefined}
              onClick={() => setTab(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>

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
              <SwipeRow key={row.key} onDelete={row.onDelete} deleteLabel={row.deleteLabel}>
                <Link href={row.href} className="lib-link" draggable={false} aria-label={`${row.title}，${row.status}，继续播放`}>
                  <span className="lib-cover">
                    <ProgrammeCoverView id={row.programmeId} title={row.title} stationId={row.stationId} bare radius={0} />
                  </span>
                  <span className="lib-copy">
                    <span className="lib-title">{row.title}</span>
                    <span className="lib-status">
                      <span className="filter-dot" style={{ background: STATIONS.find((s) => s.id === row.stationId)?.light }} />
                      {row.status}
                    </span>
                  </span>
                  <ProgressRing ratio={row.ratio} />
                </Link>
              </SwipeRow>
            ))}
          </ul>
        ) : (
          <div className="lib-empty">
            <p>
              {tab === "recent"
                ? "听过的节目会留在这里，下次从上次的位置接着听。"
                : tab === "saved"
                  ? "在播放页的“更多”里保存完整节目，它会留在这里。"
                  : "在调频页开播的节目会留在这里。"}
            </p>
            <Link href="/tune" className="pill-button">去调频</Link>
          </div>
        )}
      </div>
    </AppShell>
  );
}
