"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { api } from "../lib/api";
import { durationLabel, programPresentation } from "../lib/program-presentation";
import type { ProgramProposal } from "../lib/types";
import { isFavoriteSeed, toggleFavoriteSeed } from "../lib/user-library";
import { ProgramArtwork } from "./program-artwork";
import { WaveIcon } from "./wave-icon";

export function ProgramDetail({ seedId }: { seedId: string }) {
  const [seed, setSeed] = useState<ProgramProposal | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [favorite, setFavorite] = useState(false);
  const [shared, setShared] = useState(false);

  useEffect(() => {
    api.program(seedId)
      .then(setSeed)
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "节目暂时无法载入"));
    setFavorite(isFavoriteSeed(seedId));
  }, [seedId]);

  const presentation = useMemo(() => {
    if (!seed) return null;
    const fallback = programPresentation(seed);
    return {
      ...fallback,
      genres: seed.genre_tags.length ? seed.genre_tags.join(" · ") : fallback.genres,
      artists: seed.anchor_artists.length ? seed.anchor_artists : fallback.artists,
      route: seed.editorial_route.length ? seed.editorial_route : fallback.route,
      mood: seed.mood_tags.length ? seed.mood_tags.join(" / ") : fallback.mood,
    };
  }, [seed]);

  const share = async () => {
    if (!seed) return;
    const payload = { title: seed.title, text: seed.short_description, url: window.location.href };
    try {
      if (navigator.share) await navigator.share(payload);
      else await navigator.clipboard.writeText(window.location.href);
      setShared(true);
      window.setTimeout(() => setShared(false), 1600);
    } catch {
      // The browser share sheet can be dismissed; that is not a product error.
    }
  };

  if (error) {
    return <main className="detail-page detail-state"><Link href="/" className="round-back"><WaveIcon name="back" /></Link><p>{error}</p></main>;
  }
  if (!seed || !presentation) {
    return <main className="detail-page detail-state"><div className="loading-orb" /><p>正在准备节目卡片…</p></main>;
  }

  return (
    <main className="detail-page page-enter">
      <div className="detail-topbar">
        <Link href="/" className="round-back" aria-label="返回为你"><WaveIcon name="back" /></Link>
        <span className="detail-topbar-spacer" aria-hidden="true" />
      </div>

      <section className="detail-hero">
        <div className="detail-artwork-wrap">
          <ProgramArtwork
            title={seed.title}
            subtitle={presentation.mood}
            palette={seed.cover.palette}
            seed={seed.cover.seed}
            family={seed.cover.family}
            className="detail-artwork"
          />
        </div>

        <div className="detail-copy">
          <p className="program-kicker">WAVECAST PROGRAM</p>
          <h1>{seed.title}</h1>
          <p className="program-meta">{presentation.genres}</p>
          <p className="program-meta">{durationLabel(seed.estimated_duration_seconds)}</p>

          <div className="detail-actions">
            <Link href={`/episode/${seed.id}`} className="primary-pill">
              <WaveIcon name="play" size={18} />
              开始收听
            </Link>
            <button
              type="button"
              className={favorite ? "round-action selected" : "round-action"}
              aria-label={favorite ? "取消收藏" : "收藏"}
              onClick={() => {
                const isFavorite = toggleFavoriteSeed(seed.id);
                setFavorite(isFavorite);
                if (isFavorite) {
                  void api.recordUserEvent({ event_type: "FAVORITE", program_id: seed.id })
                    .catch(() => undefined);
                }
              }}
            >
              <WaveIcon name="heart" size={20} />
              <span>{favorite ? "已收藏" : "收藏"}</span>
            </button>
            <button type="button" className="round-action" aria-label="分享" onClick={() => void share()}>
              <WaveIcon name="share" size={20} />
              <span>{shared ? "已复制" : "分享"}</span>
            </button>
          </div>

          <p className="detail-description">{presentation.description}</p>

          <section className="detail-section">
            <h2>你可能会听到</h2>
            <div className="artist-row">
              {presentation.artists.map((artist, index) => (
                <div className="artist-pill" key={artist}>
                  <span className={"artist-avatar avatar-" + (index % 4)}>{artist.slice(0, 1)}</span>
                  <small>{artist}</small>
                </div>
              ))}
            </div>
          </section>

          <section className="detail-section route-section">
            <div className="section-title-row"><h2>节目路线</h2><span>{presentation.route.length} 章</span></div>
            <div className="route-line">
              {presentation.route.map((step, index) => (
                <span key={step}><i>{String(index + 1).padStart(2, "0")}</i>{step}</span>
              ))}
            </div>
          </section>
        </div>
      </section>
    </main>
  );
}
