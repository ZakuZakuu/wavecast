"use client";

import { useEffect, useState } from "react";

import { programmeCover } from "../../lib/cover/programme-cover";
import { canNativeShare, copyText, displayShareUrl, nativeShare, programmeShareUrl } from "../../lib/share";
import { formatFreq, stationById, type StationId } from "../../lib/stations";
import { BottomSheet } from "../bottom-sheet";
import { CloseIcon } from "../icons";
import { TypeCover } from "../cover/type-cover";

export type ShareTarget = {
  id: string;
  title: string;
  coverTitle?: string | null;
  stationId: StationId;
};

/** 分享这档节目: a link to the programme itself, not to what one person heard of it. */
export function ShareSheet({
  open,
  onClose,
  target,
}: {
  open: boolean;
  onClose: () => void;
  target: ShareTarget | null;
}) {
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);
  const [native, setNative] = useState(false);

  useEffect(() => {
    setNative(canNativeShare());
  }, []);
  useEffect(() => {
    if (!open) {
      setCopied(false);
      setFailed(false);
    }
  }, [open]);
  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 2400);
    return () => window.clearTimeout(timer);
  }, [copied]);

  if (!target) return null;
  const station = stationById(target.stationId);
  const url = programmeShareUrl(target.id);
  const cover = programmeCover({ id: target.id, title: target.title, stationId: station.id, coverTitle: target.coverTitle });

  const copy = async () => {
    const done = await copyText(url);
    setCopied(done);
    setFailed(!done);
  };
  const more = () => void nativeShare({ title: target.title, text: `${target.title}，WaveCast 上的一档节目`, url });

  return (
    <BottomSheet open={open} onClose={onClose} label="分享这档节目" tone="light" className="share-sheet">
      <div className="ss-head">
        <h2 className="ss-title">分享这档节目</h2>
        <button type="button" className="ss-close" aria-label="关闭" onClick={onClose}><CloseIcon size={22} strokeWidth={1.8} /></button>
      </div>
      <div className="ss-card">
        <span className="ss-cover"><TypeCover params={{ ...cover.params, bare: true }} radius={0} /></span>
        <span className="ss-card-text">
          <span className="ss-card-title">{target.title}</span>
          <span className="ss-card-meta">WaveCast · FM {formatFreq(station.freq)} {station.name}</span>
          <span className="ss-card-url">{displayShareUrl(url)}</span>
        </span>
      </div>
      <div className="ss-actions">
        <button type="button" className="pill-button ss-primary" onClick={() => void copy()}>
          {copied ? (
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m5 12.5 4.5 4.5L19 7" /></svg>
          ) : null}
          {copied ? "已复制" : "复制链接"}
        </button>
        {native ? (
          <button type="button" className="pill-button ss-secondary" onClick={more}>更多分享方式</button>
        ) : null}
      </div>
      <p className={failed ? "ss-note is-error" : "ss-note"} role="status">
        {failed
          ? "这台设备没让我们复制，可以长按上面的地址自己复制。"
          : "对方打开链接后，点播放才会生成属于他的一份节目，内容不一定和你听到的完全一样。"}
      </p>
    </BottomSheet>
  );
}
