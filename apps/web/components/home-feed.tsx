"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api } from "../lib/api";
import type { Seed } from "../lib/types";
import { formatSeconds } from "../lib/playback";

export function HomeFeed() {
  const [seeds, setSeeds] = useState<Seed[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.seeds().then(setSeeds).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Unable to load programs"));
  }, []);

  return (
    <main className="shell">
      <nav className="nav"><span className="brand">wavecast</span><span className="status-dot">mock runtime</span></nav>
      <section className="hero">
        <p className="eyebrow">GUIDED LISTENING</p>
        <h1>先听见一首歌，<br />故事在路上长出来。</h1>
        <p>每一个节目从可立即播放的开场开始；研究、串联与旁白只生成在你前方一点。</p>
      </section>
      <section aria-labelledby="programs-title">
        <div className="section-heading"><h2 id="programs-title">为现在准备的节目</h2><span>{seeds.length || "…"} 个提案</span></div>
        {error ? <p className="error">{error} — 请先启动 API 服务。</p> : null}
        <div className="card-grid">
          {seeds.map((seed) => (
            <Link href={`/episode/${seed.id}`} className="program-card" key={seed.id} style={{ "--base": seed.cover.palette[0], "--accent": seed.cover.palette[1], "--seed": `${seed.cover.seed % 70}%` } as React.CSSProperties}>
              <div className="cover"><span>{seed.topic}</span><i /></div>
              <div className="card-copy"><p>{formatSeconds(seed.estimated_duration_seconds)} · {seed.cover.family}</p><h3>{seed.title}</h3><span>从 {seed.opening_track_title} 开始</span></div>
            </Link>
          ))}
        </div>
      </section>
    </main>
  );
}
