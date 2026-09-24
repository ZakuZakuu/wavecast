"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api } from "../lib/api";
import type { Seed } from "../lib/types";
import { AppShell } from "./app-shell";
import { ProgramCard } from "./program-card";
import { WaveIcon } from "./wave-icon";

export function HomeFeed() {
  const [seeds, setSeeds] = useState<Seed[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.seeds()
      .then(setSeeds)
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "节目暂时无法载入"));
  }, []);

  return (
    <AppShell>
      <div className="page-header home-header">
        <div>
          <p className="program-kicker">WAVECAST</p>
          <h1>为你推荐 <WaveIcon name="chevron" size={24} /></h1>
        </div>
        <button type="button" className="icon-button soft-button" aria-label="搜索"><WaveIcon name="search" /></button>
      </div>

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
