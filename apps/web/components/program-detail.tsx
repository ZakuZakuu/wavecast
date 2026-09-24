"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { api } from "../lib/api";
import { durationLabel, programPresentation } from "../lib/program-presentation";
import type { Seed } from "../lib/types";
import { ProgramArtwork } from "./program-artwork";
import { WaveIcon } from "./wave-icon";

export function ProgramDetail({ seedId }: { seedId: string }) {
  const [seed, setSeed] = useState<Seed | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [favorite, setFavorite] = useState(false);
  const [shared, setShared] = useState(false);

  useEffect(() => {
    api.seeds()
      .then((items) => setSeed(items.find((item) => item.id === seedId) ?? null))
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "节目暂时无法载入"));
  }, [seedId]);

  const presentation = useMemo(() => seed ? programPresentation(seed) : null, [seed]);

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
        <button className="icon-button glass-button" type="button" aria-label="更多"><WaveIcon name="more" /></button>
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
              onClick={() => setFavorite((value) => !value)}
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
