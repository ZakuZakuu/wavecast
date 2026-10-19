"use client";

import { useEffect, useRef, useState } from "react";

import type { CoverParams } from "../../lib/cover/build-cover";
import type { CoverFront } from "../../lib/song-cover";
import { TypeCover } from "../cover/type-cover";

/** How long the previous song's cover stays underneath while the next one fades in. */
const FADE_MS = 400;
/** Of the cover area, the share one stacked cover takes; the rest is the offset of the one behind. */
const CARD_SHARE = 0.912;

export type LoadedCover = { current: string | null; previous: string | null };

/**
 * The song cover to show for `src`: only an image that has loaded (so the stack never opens on an
 * empty card), the one before it kept underneath for the cross-fade, and nothing at all when the
 * address is missing or the image fails.
 */
export function useLoadedCover(src: string | null): LoadedCover {
  const [shown, setShown] = useState<LoadedCover>({ current: null, previous: null });
  const settled = useRef<string | null>(null);

  useEffect(() => {
    if (!src) {
      settled.current = null;
      setShown({ current: null, previous: null });
      return;
    }
    if (settled.current === src) return;
    let cancelled = false;
    let timer: number | undefined;
    const image = new Image();
    image.referrerPolicy = "no-referrer";
    image.onload = () => {
      if (cancelled) return;
      const before = settled.current;
      settled.current = src;
      setShown({ current: src, previous: before });
      if (before) timer = window.setTimeout(() => setShown({ current: src, previous: null }), FADE_MS);
    };
    image.onerror = () => {
      if (cancelled) return;
      settled.current = null;
      setShown({ current: null, previous: null });
    };
    image.src = src;
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [src]);

  return shown;
}

function SongImage({ src, className }: { src: string; className?: string }) {
  return <img className={className} src={src} alt="" referrerPolicy="no-referrer" decoding="async" draggable={false} />;
}

/**
 * The programme's cover, or — once the song has a cover — two covers of the same size stacked with
 * a slight offset. The one in front is the one the listener is looking at; tapping the stack brings
 * the other forward.
 */
export function PlayerCover({
  params,
  size,
  song,
  front,
  onToggle,
}: {
  params: CoverParams;
  size: number;
  song: LoadedCover;
  front: CoverFront;
  onToggle: () => void;
}) {
  if (!song.current) {
    return (
      <div className="player-cover" data-drag-handle style={{ width: size, height: size }}>
        <TypeCover params={params} radius={12} />
      </div>
    );
  }
  const card = Math.round(size * CARD_SHARE);
  return (
    <div
      className="player-cover-stack"
      data-drag-handle
      data-front={front}
      style={{ width: size, height: size, ["--card" as string]: `${card}px`, ["--off" as string]: `${size - card}px` }}
    >
      <div className="player-cover-card is-show">
        <TypeCover params={params} radius={0} />
      </div>
      <div className="player-cover-card is-song">
        {song.previous ? <SongImage src={song.previous} className="player-song-image" /> : null}
        <SongImage key={song.current} src={song.current} className={`player-song-image${song.previous ? " is-entering" : ""}`} />
      </div>
      <button
        type="button"
        className="player-cover-hit"
        aria-label={front === "song" ? "查看节目封面" : "查看歌曲封面"}
        onClick={onToggle}
      />
    </div>
  );
}
