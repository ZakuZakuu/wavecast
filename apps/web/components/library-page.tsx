"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api } from "../lib/api";
import type { ProgramProposal } from "../lib/types";
import {
  emptyUserLibrary,
  readUserLibrary,
  removeSavedEpisode,
  subscribeUserLibrary,
  type RecentProgramRecord,
  type SavedEpisodeRecord,
  type UserLibraryState,
} from "../lib/user-library";
import { AppShell } from "./app-shell";
import { ProgramArtwork } from "./program-artwork";
import { ProgramCard } from "./program-card";
import { WaveIcon } from "./wave-icon";

const TABS = ["收藏", "最近收听", "已保存", "我创建的"] as const;
type Tab = typeof TABS[number];

function formatDate(timestamp: number): string {
  const formatter = new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
  });
  return formatter.format(new Date(timestamp));
}

function formatProgress(record: RecentProgramRecord): string {
  const minutes = Math.max(0, Math.round(record.progressSeconds / 60));
  return minutes > 0 ? "已听 " + minutes + " 分钟" : "刚刚开始";
}

function EpisodeLibraryRow({
  record,
  saved = false,
  onRemove,
}: {
  record: RecentProgramRecord | SavedEpisodeRecord;
  saved?: boolean;
  onRemove?: () => void;
}) {
  return (
    <article className="library-record">
      <Link
        href={"/episode/materialized/" + record.episodeId}
        className="library-record-main"
      >
        <ProgramArtwork
          title={record.title}
          subtitle={record.topic ?? "WaveCast"}
          seed={record.seedId.length * 29 + record.title.length}
          className="library-record-artwork"
        />
        <span className="library-record-copy">
          <strong>{record.title}</strong>
          <small>{record.currentTitle ?? "继续收听"}</small>
          <em>
            {saved && "savedAt" in record
              ? "保存于 " + formatDate(record.savedAt)
              : formatProgress(record)}
          </em>
        </span>
      </Link>
      {saved && onRemove ? (
        <button
          type="button"
          className="icon-button library-remove"
          aria-label={"从已保存移除 " + record.title}
          onClick={onRemove}
        >
          <WaveIcon name="close" size={16} />
        </button>
      ) : null}
    </article>
  );
}

export function LibraryPage() {
  const [tab, setTab] = useState<Tab>("最近收听");
  const [library, setLibrary] = useState<UserLibraryState>(emptyUserLibrary);
  const [favoritePrograms, setFavoritePrograms] = useState<ProgramProposal[]>([]);
  const [createdPrograms, setCreatedPrograms] = useState<ProgramProposal[]>([]);

  useEffect(() => {
    const refresh = () => setLibrary(readUserLibrary());
    refresh();
    return subscribeUserLibrary(refresh);
  }, []);

  useEffect(() => {
    let active = true;
    void Promise.all(
      library.favoriteSeedIds.map((id) => api.program(id).catch(() => null)),
    ).then((items) => {
      if (active) {
        setFavoritePrograms(items.filter((item): item is ProgramProposal => Boolean(item)));
      }
    });
    return () => {
      active = false;
    };
  }, [library.favoriteSeedIds]);

  useEffect(() => {
    let active = true;
    void Promise.all(
      library.createdProgramIds.map((id) => api.program(id).catch(() => null)),
    ).then((items) => {
      if (active) {
        setCreatedPrograms(items.filter((item): item is ProgramProposal => Boolean(item)));
      }
    });
    return () => {
      active = false;
    };
  }, [library.createdProgramIds]);

  const removeSaved = (episodeId: string) => {
    removeSavedEpisode(episodeId);
    setLibrary(readUserLibrary());
  };

  const hasContent = tab === "收藏"
    ? favoritePrograms.length > 0
    : tab === "最近收听"
      ? library.recentPrograms.length > 0
      : tab === "已保存"
        ? library.savedEpisodes.length > 0
        : tab === "我创建的"
          ? createdPrograms.length > 0
          : false;

  return (
    <AppShell>
      <div className="page-header library-header">
        <div><p className="program-kicker">YOUR PROGRAMS</p><h1>节目库</h1></div>
        <span className="profile-dot">R</span>
      </div>

      <div className="library-tabs" role="tablist" aria-label="节目库分类">
        {TABS.map((item) => (
          <button
            key={item}
            type="button"
            role="tab"
            aria-selected={tab === item}
            className={tab === item ? "active" : ""}
            onClick={() => setTab(item)}
          >
            {item}
          </button>
        ))}
      </div>

      {tab === "收藏" && favoritePrograms.length ? (
        <section className="library-list">
          {favoritePrograms.map((program) => <ProgramCard seed={program} compact key={program.id} />)}
        </section>
      ) : null}

      {tab === "最近收听" && library.recentPrograms.length ? (
        <section className="library-record-list">
          {library.recentPrograms.map((record) => (
            <EpisodeLibraryRow record={record} key={record.episodeId} />
          ))}
        </section>
      ) : null}

      {tab === "已保存" && library.savedEpisodes.length ? (
        <section className="library-record-list">
          {library.savedEpisodes.map((record) => (
            <EpisodeLibraryRow
              record={record}
              saved
              onRemove={() => removeSaved(record.episodeId)}
              key={record.episodeId}
            />
          ))}
        </section>
      ) : null}

      {tab === "我创建的" && createdPrograms.length ? (
        <section className="library-list">
          {createdPrograms.map((program) => (
            <ProgramCard seed={program} compact key={program.id} />
          ))}
        </section>
      ) : null}

      {!hasContent ? (
        <section className="library-empty">
          <div className="empty-disc"><i /></div>
          <h2>
            {tab === "收藏"
              ? "还没有收藏的节目"
              : tab === "最近收听"
                ? "还没有收听记录"
                : tab === "已保存"
                  ? "还没有保存完整节目"
                  : "还没有自己调出的节目"}
          </h2>
          <p>
            {tab === "收藏"
              ? "在节目详情点一下收藏，它就会留在这里。"
              : tab === "最近收听"
                ? "开始收听后，进度会自动留在这里。"
                : tab === "已保存"
                  ? "完整生成节目后，可以把这个固定版本保存下来。"
                  : "去调频页说出你想听什么，生成的节目提案会留在这里。"}
          </p>
        </section>
      ) : null}
    </AppShell>
  );
}
