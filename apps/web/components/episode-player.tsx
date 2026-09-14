"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { api } from "../lib/api";
import { formatSeconds, isSeekAllowed } from "../lib/playback";
import { usePlayerStore } from "../lib/player-store";
import type { LiveEpisode } from "../lib/types";
import { TonePlayer } from "./tone-player";

export function EpisodePlayer({ seedId }: { seedId: string }) {
  const { episode, isPlaying, setEpisode, setPlaying } = usePlayerStore();
  const [error, setError] = useState<string | null>(null);
  const localEpisode = episode?.seed_id === seedId ? episode : null;
  const current = useMemo(() => localEpisode?.segments.find((segment) => segment.id === localEpisode.current_segment_id), [localEpisode]);

  useEffect(() => {
    let cancelled = false;
    api.start(seedId).then((created) => {
      if (!cancelled) setEpisode(created);
    }).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Unable to start episode"));
    return () => { cancelled = true; };
  }, [seedId, setEpisode]);

  useEffect(() => {
    if (!localEpisode?.is_listener_active || localEpisode.state === "MATERIALIZED") return;
    const interval = window.setInterval(() => {
      api.advance(localEpisode.id).then(setEpisode).catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(interval);
  }, [localEpisode?.id, localEpisode?.is_listener_active, localEpisode?.state, setEpisode]);

  async function update(operation: Promise<LiveEpisode>) {
    try { setEpisode(await operation); setError(null); } catch (reason) { setError(reason instanceof Error ? reason.message : "Player action failed"); }
  }

  if (error && !localEpisode) return <main className="shell"><Link href="/">← Home</Link><p className="error">{error} — 请先启动 API 服务。</p></main>;
  if (!localEpisode) return <main className="shell"><p className="eyebrow">STARTING THE OPENING TRACK</p><h1>正在接入节目…</h1></main>;

  const generatedPercent = Math.round((localEpisode.generated_frontier_seconds / localEpisode.estimated_total_seconds) * 100);
  return (
    <main className="shell player-shell">
      <TonePlayer segment={current} playing={isPlaying && localEpisode.is_listener_active} />
      <nav className="nav"><Link href="/">← 返回节目</Link><span className="status-dot">{localEpisode.state === "MATERIALIZED" ? "fixed episode" : "building ahead"}</span></nav>
      <section className="now-playing">
        <p className="eyebrow">{current?.kind === "MUSIC" ? "NOW PLAYING" : "HOST ON MIC"}</p>
        <h1>{current?.title}</h1>
        <p>{current?.artist ?? current?.narration_text ?? "正在准备下一段"}</p>
        <div className="controls">
          <button onClick={() => setPlaying(!isPlaying)}>{isPlaying ? "暂停" : "继续"}</button>
          <button onClick={() => void update(api.next(localEpisode.id))}>下一章节</button>
          <button className="quiet" onClick={() => void update(api.materialize(localEpisode.id))}>生成完整节目</button>
        </div>
      </section>
      <section className="timeline" aria-label="episode timeline">
        <div className="timeline-label"><span>已生成 {formatSeconds(localEpisode.generated_frontier_seconds)}</span><span>预计 {formatSeconds(localEpisode.estimated_total_seconds)}</span></div>
        <input aria-label="Seek within generated audio" type="range" min="0" max={localEpisode.estimated_total_seconds} value={localEpisode.playback_position_seconds} onChange={(event) => {
          const value = Number(event.target.value);
          if (isSeekAllowed(localEpisode, value)) void update(api.seek(localEpisode.id, value));
        }} style={{ "--generated": `${generatedPercent}%` } as React.CSSProperties} />
        <p>亮色区域可以回听；未生成的未来仍在制作中。</p>
      </section>
      <section className="segment-list">
        {localEpisode.segments.map((segment) => <article className={`segment ${segment.state === "PLANNED" ? "planned" : "ready"}`} key={segment.id}>
          <span>{segment.kind === "MUSIC" ? "♫" : "◌"}</span><div><strong>{segment.title}</strong><p>{segment.artist ?? "旁白"} · {formatSeconds(segment.actual_duration_seconds ?? segment.planned_duration_seconds)}</p></div><small>{segment.state.replace("_", " ")}</small>
        </article>)}
      </section>
      <div className="session-actions">
        {localEpisode.is_listener_active ? <button className="quiet" onClick={() => void update(api.leave(localEpisode.id))}>离开并停止后续生成</button> : <button onClick={() => void update(api.resume(localEpisode.id))}>返回并继续生成</button>}
        {error ? <p className="error">{error}</p> : null}
      </div>
    </main>
  );
}
