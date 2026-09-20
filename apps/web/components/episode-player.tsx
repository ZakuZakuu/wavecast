"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "../lib/api";
import { subscribeToEpisodeEvents } from "../lib/episode-events";
import { formatSeconds, isSeekAllowed, nextVisibleSegment, playbackAnchor, reconcileBrowserPosition, segmentStart } from "../lib/playback";
import { usePlayerStore } from "../lib/player-store";
import type { LiveEpisode } from "../lib/types";
import { AudioPlayer } from "./audio-player";

export function EpisodePlayer({ seedId, episodeId }: { seedId?: string; episodeId?: string }) {
  const { episode, setEpisode } = usePlayerStore();
  const [error, setError] = useState<string | null>(null);
  const [browserPosition, setBrowserPosition] = useState(0);
  const episodeIdRef = useRef<string | null>(null);
  const checkpointRef = useRef<number>(-1);
  const browserPositionRef = useRef(0);
  const playbackAnchorRef = useRef<ReturnType<typeof playbackAnchor>>(null);
  const localEpisode = episode
    && (episodeId ? episode.id === episodeId : episode.seed_id === seedId)
    ? episode
    : null;
  const current = useMemo(
    () => localEpisode?.segments.find((segment) => segment.id === localEpisode.current_segment_id),
    [localEpisode],
  );

  useEffect(() => {
    let mounted = true;
    const leaveOnPageExit = () => {
      if (episodeIdRef.current) {
        void api.checkpoint(episodeIdRef.current, browserPositionRef.current);
        navigator.sendBeacon(`/api/episodes/${episodeIdRef.current}/leave`);
      }
    };
    window.addEventListener("pagehide", leaveOnPageExit);
    const load = episodeId ? api.get(episodeId) : api.start(seedId!);
    load.then((started) => {
      episodeIdRef.current = started.id;
      if (mounted) setEpisode(started);
      else void api.leave(started.id);
    }).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Unable to start episode"));
    return () => {
      mounted = false;
      window.removeEventListener("pagehide", leaveOnPageExit);
      if (episodeIdRef.current) void api.leave(episodeIdRef.current);
    };
  }, [episodeId, seedId, setEpisode]);

  useEffect(() => {
    if (!localEpisode) return;
    return subscribeToEpisodeEvents(localEpisode.id, (incoming) => {
      setEpisode(incoming);
    });
  }, [localEpisode?.id, setEpisode]);

  useEffect(() => {
    const position = reconcileBrowserPosition(
      browserPositionRef.current,
      playbackAnchorRef.current,
      localEpisode,
    );
    setBrowserPosition(position);
    browserPositionRef.current = position;
    playbackAnchorRef.current = playbackAnchor(localEpisode);
  }, [localEpisode?.current_segment_id, localEpisode?.playback_position_seconds]);

  useEffect(() => {
    if (!localEpisode?.is_listener_active) return;
    let syncing = false;
    const synchronize = async () => {
      if (syncing) return;
      syncing = true;
      try {
        let updated = await api.heartbeat(localEpisode.id);
        if (updated.state !== "MATERIALIZED") updated = await api.ensureBuffer(updated.id);
        setEpisode(updated);
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "Playback synchronization failed");
      } finally {
        syncing = false;
      }
    };
    void synchronize();
    const interval = window.setInterval(() => void synchronize(), 10_000);
    return () => window.clearInterval(interval);
  }, [localEpisode?.id, localEpisode?.is_listener_active, setEpisode]);

  async function update(operation: Promise<LiveEpisode>) {
    try {
      setEpisode(await operation);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Player action failed");
    }
  }

  const completeBrowserSegment = useCallback(() => {
    if (localEpisode?.is_playing) void update(api.completed(localEpisode.id));
  }, [localEpisode?.id, localEpisode?.is_playing]);

  const handleAudioPosition = useCallback((segmentPosition: number) => {
    if (!localEpisode || !current) return;
    const position = Math.floor(segmentStart(localEpisode, current.id) + Math.max(0, segmentPosition));
    setBrowserPosition(position);
    browserPositionRef.current = position;
    if (position > localEpisode.playback_position_seconds && position % 5 === 0 && checkpointRef.current !== position) {
      checkpointRef.current = position;
      void api.checkpoint(localEpisode.id, position);
    }
  }, [current, localEpisode]);

  const pausePlayback = useCallback(async () => {
    if (!localEpisode) return;
    await update(api.checkpoint(localEpisode.id, browserPosition));
    await update(api.pause(localEpisode.id));
  }, [browserPosition, localEpisode]);

  if (error && !localEpisode) {
    return <main className="shell"><Link href="/">← Home</Link><p className="error">{error} — 请先启动 API 服务。</p></main>;
  }
  if (!localEpisode) {
    return <main className="shell"><p className="eyebrow">STARTING THE OPENING TRACK</p><h1>正在接入节目…</h1></main>;
  }

  const generatedPercent = Math.round((localEpisode.generated_frontier_seconds / localEpisode.timeline_duration_seconds) * 100);
  const currentOffset = current
    ? Math.max(0, browserPosition - segmentStart(localEpisode, current.id))
    : 0;
  const upcoming = current ? nextVisibleSegment(localEpisode) : undefined;
  return (
    <main className="shell player-shell">
      <AudioPlayer
        segment={current}
        playing={localEpisode.is_playing && localEpisode.is_listener_active}
        positionSeconds={currentOffset}
        onPositionChange={handleAudioPosition}
        onEnded={completeBrowserSegment}
        onError={() => setError("Audio source failed")}
      />
      <nav className="nav"><Link href="/">← 返回节目</Link><span className="status-dot">{localEpisode.state === "MATERIALIZED" ? "fixed episode" : "building ahead"}</span></nav>
      <section className="now-playing">
        <p className="eyebrow">{localEpisode.title ?? "GUIDED LISTENING"}</p>
        <p className="eyebrow">{current?.kind === "MUSIC" ? "NOW PLAYING" : "HOST ON MIC"}</p>
        <h1>{current?.title}</h1>
        <p>{current?.artist ?? current?.narration_text ?? "正在准备下一段"}</p>
        <p className="eyebrow">接下来：{upcoming?.title ?? "正在准备"}{upcoming?.artist ? ` · ${upcoming.artist}` : ""}</p>
        <div className="controls">
          {localEpisode.is_playing
            ? <button onClick={() => void pausePlayback()}>暂停</button>
            : <button onClick={() => void update(api.resume(localEpisode.id))}>继续</button>}
          <button onClick={() => void update(api.next(localEpisode.id))}>下一章节</button>
          <button className="quiet" onClick={() => void update(api.materialize(localEpisode.id))}>生成完整节目</button>
        </div>
      </section>
      <section className="timeline" aria-label="episode timeline">
        <div className="timeline-label"><span>可回听 {formatSeconds(localEpisode.generated_frontier_seconds)}</span><span>节目约 {formatSeconds(localEpisode.program_estimated_duration_seconds)}</span></div>
        <input aria-label="Seek within generated audio" type="range" min="0" max={localEpisode.generated_frontier_seconds} value={browserPosition} onChange={(event) => {
          const value = Number(event.target.value);
          if (isSeekAllowed(localEpisode, value)) void update(api.seek(localEpisode.id, value));
        }} style={{ "--generated": `${generatedPercent}%` } as React.CSSProperties} />
        <p>亮色区域可以回听；当前时间轴 {formatSeconds(localEpisode.timeline_duration_seconds)}，节目承诺不会随 mock 片段缩短。</p>
      </section>
      <section className="segment-list">
        {localEpisode.segments.map((segment) => <article className={`segment ${segment.state === "PLANNED" || segment.state === "SKIPPED" ? "planned" : "ready"}`} key={segment.id}>
          <span>{segment.kind === "MUSIC" ? "♫" : "◌"}</span><div><strong>{segment.title}</strong><p>{segment.artist ?? "旁白"} · {formatSeconds(segment.duration_seconds)}</p></div><small>{segment.state.replace("_", " ")}</small>
        </article>)}
      </section>
      <div className="session-actions">
        {localEpisode.is_listener_active ? <button className="quiet" onClick={() => void update(api.leave(localEpisode.id))}>离开并停止后续生成</button> : <button onClick={() => void update(api.resume(localEpisode.id))}>返回并继续生成</button>}
        {error ? <p className="error">{error}</p> : null}
      </div>
    </main>
  );
}
