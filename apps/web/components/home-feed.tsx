"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { api } from "../lib/api";
import type { Seed } from "../lib/types";
import { AppShell } from "./app-shell";
import { ProgramCard } from "./program-card";
import { WaveIcon } from "./wave-icon";

export function HomeFeed() {
  const [seeds, setSeeds] = useState<Seed[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");

  useEffect(() => {
    api.seeds()
      .then(setSeeds)
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "节目暂时无法载入"));
  }, []);

  const searchResults = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    if (!needle) return seeds;
    return seeds.filter((seed) =>
      [
        seed.title,
        seed.topic,
        seed.short_description,
        seed.opening_track_title,
        seed.opening_track_artist,
      ].some((value) => value.toLocaleLowerCase().includes(needle)),
    );
  }, [query, seeds]);

  return (
    <AppShell>
      <div className="page-header home-header">
        <div>
          <p className="program-kicker">WAVECAST</p>
          <h1>为你推荐 <WaveIcon name="chevron" size={24} /></h1>
        </div>
        <button
          type="button"
          className={searchOpen ? "icon-button soft-button active" : "icon-button soft-button"}
          aria-label={searchOpen ? "关闭搜索" : "搜索"}
          aria-expanded={searchOpen}
          onClick={() => {
            setSearchOpen((value) => !value);
            if (searchOpen) setQuery("");
          }}
        >
          <WaveIcon name={searchOpen ? "close" : "search"} />
        </button>
      </div>

      {searchOpen ? (
        <section className="home-search-panel page-enter" aria-label="搜索节目">
          <div className="home-search-field">
            <WaveIcon name="search" size={18} />
            <input
              autoFocus
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索节目、风格、艺人或歌曲"
              aria-label="搜索节目、风格、艺人或歌曲"
            />
            {query ? (
              <button type="button" aria-label="清除搜索" onClick={() => setQuery("")}>
                <WaveIcon name="close" size={15} />
              </button>
            ) : null}
          </div>
          <div className="home-search-summary">
            <span>{query ? "搜索结果" : "全部节目"}</span>
            <small>{searchResults.length} 个</small>
          </div>
          {searchResults.length ? (
            <div className="home-search-results">
              {searchResults.map((seed) => <ProgramCard seed={seed} compact key={"search-" + seed.id} />)}
            </div>
          ) : (
            <div className="home-search-empty">
              <p>没有找到匹配的节目。</p>
              <Link href="/tune">试试自己调一档</Link>
            </div>
          )}
        </section>
      ) : null}

      {error ? <p className="inline-error">{error}</p> : null}

      <section className="feed-section">
        <div className="program-shelf" aria-label="为你推荐的节目">
          {seeds.map((seed) => <ProgramCard seed={seed} key={seed.id} />)}
          {!seeds.length && !error ? Array.from({ length: 4 }).map((_, index) => <div className="program-skeleton" key={index} />) : null}
        </div>
      </section>

      <section className="feed-section">
        <div className="section-title-row"><h2>值得一听</h2><span>本周精选</span></div>
        <div className="compact-program-list">
          {seeds.map((seed) => <ProgramCard seed={seed} compact key={"compact-" + seed.id} />)}
        </div>
      </section>

      <section className="editorial-banner">
        <div>
          <p className="program-kicker">GUIDED LISTENING</p>
          <h2>不是歌单，是一档为你排好的节目。</h2>
          <p>音乐先开始，故事只在你前方一点点长出来。</p>
        </div>
        <Link href="/tune" className="banner-action"><WaveIcon name="sparkle" />去调一档</Link>
      </section>
    </AppShell>
  );
}
