"use client";

import { useEffect, useState } from "react";

import { api } from "../lib/api";
import type { Seed } from "../lib/types";
import { usePlayerStore } from "../lib/player-store";
import { AppShell } from "./app-shell";
import { ProgramCard } from "./program-card";

const TABS = ["收藏", "最近收听", "已保存", "我创建的"] as const;
type Tab = typeof TABS[number];

export function LibraryPage() {
  const [tab, setTab] = useState<Tab>("最近收听");
  const [seeds, setSeeds] = useState<Seed[]>([]);
  const episode = usePlayerStore((state) => state.episode);

  useEffect(() => {
    api.seeds().then(setSeeds).catch(() => setSeeds([]));
  }, []);

  const visible = tab === "最近收听" ? seeds : [];

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

      {tab === "最近收听" && episode ? (
        <section className="continue-card">
          <div>
            <span>继续收听</span>
            <strong>{episode.title ?? "上一档节目"}</strong>
            <small>{episode.segments.find((item) => item.id === episode.current_segment_id)?.title ?? "回到节目"}</small>
          </div>
        </section>
      ) : null}

      {visible.length ? (
        <section className="library-list">
          {visible.map((seed) => <ProgramCard seed={seed} compact key={seed.id} />)}
        </section>
      ) : (
        <section className="library-empty">
          <div className="empty-disc"><i /></div>
          <h2>{tab === "收藏" ? "还没有收藏的节目" : tab === "我创建的" ? "还没有自己调出的节目" : "这里还空着"}</h2>
          <p>{tab === "收藏" ? "遇到想再听一次的节目，就把它留在这里。" : "等这一部分接上账号与节目库后，内容会出现在这里。"}</p>
        </section>
      )}
    </AppShell>
  );
}
