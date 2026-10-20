"use client";

import { useEffect, useRef, useState } from "react";

import type { CoverParams } from "../../lib/cover/build-cover";
import type { CoverFront } from "../../lib/song-cover";
import { TypeCover } from "../cover/type-cover";

/** How long the previous song's cover stays underneath while the next one fades in. */
const FADE_MS = 400;
/** How long a swap of the two stacked covers runs (player.css: --swap). The marker stays a little longer. */
const SWAP_MS = 250;
/** Of the cover area, the share one stacked cover takes; the rest is the offset of the one behind. */
const CARD_SHARE = 0.912;

export type LoadedCover = { current: string | null; previous: string | null };

// Covers loaded earlier in this visit: coming back to the player shows the stack at once instead of
// the programme's cover alone for as long as the picture takes to arrive.
const loadedBefore = new Set<string>();

/**
 * The song cover to show for `src`: only an image that has loaded (so the stack never opens on an
 * empty card), the one before it kept underneath for the cross-fade, and nothing at all when the
 * address is missing or the image fails.
 */
export function useLoadedCover(src: string | null): LoadedCover {
  const known = src !== null && loadedBefore.has(src) ? src : null;
  const [shown, setShown] = useState<LoadedCover>({ current: known, previous: null });
  const settled = useRef<string | null>(known);

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
      loadedBefore.add(src);
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
  // Which way the stack is turning, for as long as it turns. Only a change of `front` while the stack is
  // already on screen counts: the stack appearing is not a swap, so nothing animates then.
  const [swap, setSwap] = useState<"to-show" | "to-song" | null>(null);
  const previousFront = useRef(front);
  const wasStacked = useRef(false);
  const swapTimer = useRef<number | undefined>(undefined);
  const stacked = Boolean(song.current);
  useEffect(() => {
    const turned = previousFront.current !== front;
    previousFront.current = front;
    const wasOn = wasStacked.current;
    wasStacked.current = stacked;
    if (!turned || !wasOn || !stacked) return;
    setSwap(front === "show" ? "to-show" : "to-song");
    window.clearTimeout(swapTimer.current);
    swapTimer.current = window.setTimeout(() => setSwap(null), SWAP_MS + 50);
  }, [front, stacked]);
  useEffect(() => () => window.clearTimeout(swapTimer.current), []);

  if (!song.current) {
    return (
      <div key="single" className="player-cover" data-drag-handle style={{ width: size, height: size }}>
        <TypeCover params={params} radius={12} />
      </div>
    );
  }
  const card = Math.round(size * CARD_SHARE);
  return (
    <div
      key="stack"
      className="player-cover-stack"
      data-drag-handle
      data-front={front}
      data-swap={swap ?? undefined}
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
