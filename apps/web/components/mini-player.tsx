"use client";

import Link from "next/link";
import { useState } from "react";

import { api } from "../lib/api";
import { usePlayerStore } from "../lib/player-store";
import { ProgramArtwork } from "./program-artwork";
import { WaveIcon } from "./wave-icon";

export function MiniPlayer() {
  const { episode, setEpisode } = usePlayerStore();
  const [busy, setBusy] = useState(false);
  if (!episode) return null;

  const current = episode.segments.find((segment) => segment.id === episode.current_segment_id);
  const title = episode.title ?? "正在收听";
  const href = `/episode/materialized/\${episode.id}`;

  const togglePlayback = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const next = episode.is_playing && episode.is_listener_active
        ? await api.pause(episode.id)
        : await api.resume(episode.id);
      setEpisode(next);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mini-player-wrap">
      <div className="mini-player">
        <Link href={href} className="mini-player-main">
          <ProgramArtwork title={title} seed={episode.seed_id.length * 17} className="mini-artwork" />
          <span className="mini-player-copy">
            <strong>{title}</strong>
            <small>{current?.title ?? "继续收听"}</small>
          </span>
        </Link>
        <button
          className="icon-button mini-play"
          type="button"
          aria-label={episode.is_playing ? "暂停" : "继续播放"}
          onClick={() => void togglePlayback()}
          disabled={busy}
        >
          <WaveIcon name={episode.is_playing ? "pause" : "play"} size={20} />
        </button>
      </div>
    </div>
  );
}
