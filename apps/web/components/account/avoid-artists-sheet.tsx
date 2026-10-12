"use client";

import { useEffect, useState } from "react";

import { api } from "../../lib/api";
import { removeLessLikeThisArtist } from "../../lib/listener-feedback";
import { BottomSheet } from "../bottom-sheet";

/** 少放的歌手: the artists marked with 少放这类, with a way to take each one back. */
export function AvoidArtistsSheet({
  open,
  onClose,
  userId,
  artists,
  onChange,
}: {
  open: boolean;
  onClose: () => void;
  userId: string;
  artists: string[];
  onChange: (next: string[]) => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) setError(null);
  }, [open]);

  const remove = async (artist: string) => {
    setBusy(artist);
    setError(null);
    try {
      const saved = await api.stopAvoidingArtist(artist, userId);
      removeLessLikeThisArtist(artist);
      onChange(saved.avoid_artists ?? []);
    } catch {
      setError("暂时没能取消，稍后再试");
    } finally {
      setBusy(null);
    }
  };

  return (
    <BottomSheet open={open} onClose={onClose} label="少放的歌手" tone="light" className="avoid-sheet">
      <div className="avoid-body">
        <h2 className="avoid-title">少放的歌手</h2>
        <p className="avoid-note">推荐和调频会少放他们。取消后，之后的推荐就不再回避。</p>
        {artists.length ? (
          <ul className="avoid-list">
            {artists.map((artist) => (
              <li key={artist}>
                <span className="avoid-name">{artist}</span>
                <button type="button" className="avoid-remove" onClick={() => void remove(artist)} disabled={busy !== null}>
                  {busy === artist ? "正在取消…" : "取消"}
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="avoid-empty">还没有。播放时点“少放这类”，那首歌的歌手会出现在这里。</p>
        )}
        {error ? <p className="avoid-error" role="alert">{error}</p> : null}
      </div>
    </BottomSheet>
  );
}
