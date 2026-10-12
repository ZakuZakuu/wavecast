"use client";

import { programmeCover } from "../../lib/cover/programme-cover";
import { stationById, type StationId } from "../../lib/stations";
import { pickMeta } from "../../lib/home-picks";
import { BottomSheet } from "../bottom-sheet";
import { TypeCover } from "../cover/type-cover";

/** What the sheet shows about a programme that has not been generated yet. */
export type ProgrammePreview = {
  id: string;
  stationId: StationId;
  title: string;
  coverTitle?: string;
  minutes: number | null;
  /** One sentence about what the listener will be taken through. */
  description?: string;
  /** Why it fits this listener (recommendations only). */
  reason?: string;
};

/**
 * The programme detail: shown before anything is generated, so the listener can see what a
 * programme promises and only then press play (the programme is made at that point).
 */
export function ProgrammeSheet({
  preview,
  open,
  busy,
  onClose,
  onPlay,
}: {
  preview: ProgrammePreview | null;
  open: boolean;
  busy: boolean;
  onClose: () => void;
  onPlay: () => void;
}) {
  if (!preview) return null;
  const station = stationById(preview.stationId);
  const cover = programmeCover({
    id: preview.id,
    title: preview.coverTitle ?? preview.title,
    stationId: station.id,
  });
  return (
    <BottomSheet open={open} onClose={onClose} label={preview.title} tone="light" height="min(720px, calc(100dvh - 24px))" className="programme-sheet">
      <div className="ps-scroll">
        <span className="ps-cover">
          <TypeCover params={cover.params} radius={16} />
        </span>
        <h2 className="ps-title">{preview.title}</h2>
        <p className="ps-meta">{pickMeta(station.name, preview.minutes)}</p>
        {preview.description ? <p className="ps-description">{preview.description}</p> : null}
        {preview.reason ? (
          <p className="ps-reason">
            <span className="ps-reason-label">为什么推荐</span>
            {preview.reason}
          </p>
        ) : null}
        <p className="ps-note">点播放之后，才会开始准备这档节目。</p>
      </div>
      <button type="button" className="pill-button ps-play" onClick={onPlay} disabled={busy}>
        {busy ? "正在准备…" : "播放"}
      </button>
    </BottomSheet>
  );
}
