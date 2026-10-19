"use client";

import Link from "next/link";
import { useMemo } from "react";

import { programmeCover } from "../../lib/cover/programme-cover";
import { stationById, stationForProgramme } from "../../lib/stations";
import type { PublicShelfState } from "../../lib/public-shelf";
import type { PublicShelfItem } from "../../lib/types";
import { TypeCover } from "../cover/type-cover";

function ShelfCard({ item }: { item: PublicShelfItem }) {
  const station = item.station ? stationById(item.station) : stationForProgramme(item.id, item.title);
  // A published programme's cover is made from its own id, so it looks the same wherever it is seen.
  const cover = useMemo(
    () => programmeCover({ id: item.id, title: item.cover_title ?? item.title, stationId: station.id }),
    [item.cover_title, item.id, item.title, station.id],
  );
  const minutes = Math.max(1, Math.round(item.estimated_duration_seconds / 60));
  return (
    <Link
      href={`/program/${encodeURIComponent(item.id)}`}
      className="pick pick-link"
      aria-label={`${item.title}，${station.name}，约 ${minutes} 分钟`}
    >
      <span className="pick-cover">
        <TypeCover params={cover.params} radius={0} />
      </span>
      <span className="pick-text">
        <span className="pick-title">{item.title}</span>
        <span className="pick-meta pick-meta-station">
          <span className="filter-dot" style={{ background: station.light }} aria-hidden="true" />
          {station.name} · {minutes} 分钟
        </span>
      </span>
    </Link>
  );
}

/** 大家都在听: programmes other people made public, played as they are. Left out when there are too few. */
export function PublicShelf({ shelf }: { shelf: PublicShelfState }) {
  if (shelf.hidden) return null;
  const waiting = shelf.loading || shelf.refreshing;
  return (
    <section className="home-section" aria-labelledby="home-public" data-guide="home-public">
      <div className="section-title-row">
        <h2 id="home-public" className="section-title">大家都在听</h2>
        {shelf.atEnd && !waiting ? (
          <span className="pick-end">已经看完了</span>
        ) : (
          <button type="button" className="pick-refresh" onClick={shelf.refresh} disabled={waiting}>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><polyline points="23 4 23 10 17 10" /><polyline points="1 20 1 14 7 14" /><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" /></svg>
            换一批
          </button>
        )}
      </div>
      <div className="pick-rail" aria-busy={waiting}>
        {waiting
          ? Array.from({ length: 4 }).map((_, index) => <span key={index} className="pick-skeleton" aria-hidden="true" />)
          : shelf.items.map((item) => <ShelfCard key={item.id} item={item} />)}
      </div>
    </section>
  );
}
