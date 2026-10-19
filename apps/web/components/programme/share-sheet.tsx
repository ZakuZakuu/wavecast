"use client";

import { useEffect, useState, type ReactNode } from "react";

import { api, ApiRequestError } from "../../lib/api";
import { programmeCover } from "../../lib/cover/programme-cover";
import { isBeingMade, unwatchPublication, usePublication, watchPublication } from "../../lib/publications";
import {
  canNativeShare, copyText, displayShareUrl, isGeneratedProgramme, nativeShare, programmeShareUrl, publishedShareUrl,
} from "../../lib/share";
import { formatFreq, stationById, type StationId } from "../../lib/stations";
import type { FullVersionState, PublicationItem, Visibility } from "../../lib/types";
import { BottomSheet } from "../bottom-sheet";
import { CheckIcon, CloseIcon } from "../icons";
import { TypeCover } from "../cover/type-cover";
import { Segmented } from "../segmented";

export type ShareTarget = {
  /** The programme being shared: a generated one of the listener's own, a published one, or a built-in one. */
  id: string;
  title: string;
  coverTitle?: string | null;
  stationId: StationId;
  /** The listener's own episode of it, when they have one (it tells whether the 完整版 is made). */
  episodeId?: string | null;
};

/** 分享这档节目: a link to the programme itself, never to what one person heard of it. */
export function ShareSheet({ open, onClose, target }: { open: boolean; onClose: () => void; target: ShareTarget | null }) {
  if (!target) return null;
  // Only a generated programme of the listener's own needs publishing; a published one already has
  // its link, and a built-in one is its own page.
  return isGeneratedProgramme(target.id)
    ? <PublishSheet open={open} onClose={onClose} target={target} />
    : <LinkSheet open={open} onClose={onClose} target={target} />;
}

function useCopy(url: string) {
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);
  const [native, setNative] = useState(false);
  useEffect(() => setNative(canNativeShare()), []);
  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 2400);
    return () => window.clearTimeout(timer);
  }, [copied]);
  const copy = async () => {
    const done = await copyText(url);
    setCopied(done);
    setFailed(!done);
  };
  return { copied, failed, native, copy, reset: () => { setCopied(false); setFailed(false); } };
}

function Frame({
  open, onClose, target, url, children,
}: { open: boolean; onClose: () => void; target: ShareTarget; url?: string; children: ReactNode }) {
  const station = stationById(target.stationId);
  const cover = programmeCover({ id: target.id, title: target.title, stationId: station.id, coverTitle: target.coverTitle });
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
          {url ? <span className="ss-card-url">{displayShareUrl(url)}</span> : null}
        </span>
      </div>
      {children}
    </BottomSheet>
  );
}

/** The link of a programme that needs nothing made: a built-in one, or one already published. */
function LinkSheet({ open, onClose, target }: { open: boolean; onClose: () => void; target: ShareTarget }) {
  const published = target.id.startsWith("pub-");
  const url = published ? publishedShareUrl(target.id, target.id) : programmeShareUrl(target.id);
  const { copied, failed, native, copy, reset } = useCopy(url);
  useEffect(() => {
    if (!open) reset();
  }, [open]);
  return (
    <Frame open={open} onClose={onClose} target={target} url={url}>
      <LinkActions url={url} title={target.title} copied={copied} native={native} copy={copy} />
      <p className={failed ? "ss-note is-error" : "ss-note"} role="status">
        {failed
          ? "这台设备没让我们复制，可以长按上面的地址自己复制。"
          : published
            ? "对方打开链接，直接听这一份节目，不用再生成。"
            : "对方打开链接后，点播放才会生成属于他的一份节目，内容不一定和你听到的完全一样。"}
      </p>
    </Frame>
  );
}

function LinkActions({
  url, title, copied, native, copy,
}: { url: string; title: string; copied: boolean; native: boolean; copy: () => Promise<void> }) {
  return (
    <div className="ss-actions">
      <button type="button" className="pill-button ss-primary" onClick={() => void copy()}>
        {copied ? <CheckIcon size={20} strokeWidth={2.2} /> : null}
        {copied ? "已复制" : "复制链接"}
      </button>
      {native ? (
        <button
          type="button"
          className="pill-button ss-secondary"
          onClick={() => void nativeShare({ title, text: `${title}，WaveCast 上的一档节目`, url })}
        >
          更多分享方式
        </button>
      ) : null}
    </div>
  );
}

type Problem = { title: string; body: string; primary: string; secondary?: string; toLibrary?: boolean };

function problemFor(error: unknown): Problem {
  if (error instanceof ApiRequestError && error.code === "limit") {
    return { title: "分享的节目已经够多了", body: error.message, primary: "去节目库", secondary: "先不发布", toLibrary: true };
  }
  if (error instanceof ApiRequestError && (error.code === "space" || error.code === "busy")) {
    return { title: "现在发布不了", body: error.message, primary: "知道了" };
  }
  if (error instanceof ApiRequestError && error.status === 429) {
    return { title: "现在不能再准备了", body: error.message, primary: "知道了" };
  }
  return { title: "没有发布成功", body: "过一会儿再试一次。", primary: "知道了" };
}

const VISIBILITY_LABEL: Record<Visibility, string> = { link: "知道链接的人", public: "所有人" };
const VISIBILITY_HINT: Record<Visibility, string> = {
  link: "只有拿到链接的人能听，不会出现在首页。",
  public: "也会出现在首页的「大家都在听」。",
};

/** Sharing a generated programme: ask for its 完整版, wait for the mix, then hand over the link. */
function PublishSheet({ open, onClose, target }: { open: boolean; onClose: () => void; target: ShareTarget }) {
  const { item, setItem } = usePublication(target.id, open);
  const [full, setFull] = useState<FullVersionState | null>(null);
  const [choice, setChoice] = useState<Visibility>("link");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<Problem | null>(null);
  const [revoked, setRevoked] = useState(false);
  // The link is only shown once it opens: before that the card has nothing to point at.
  const url = item?.status === "published" ? publishedShareUrl(item.id, target.id) : undefined;
  const { copied, failed, native, copy, reset } = useCopy(url ?? "");

  useEffect(() => {
    if (open) return;
    reset();
    setProblem(null);
    setRevoked(false);
  }, [open]);

  // Whether the programme's 完整版 is made already decides what is asked first.
  useEffect(() => {
    if (!open || item !== null || !target.episodeId) {
      setFull(null);
      return;
    }
    let active = true;
    api.fullVersionStatuses([target.episodeId])
      .then((items) => {
        if (active) setFull(items[0]?.status ?? "none");
      })
      .catch(() => {
        if (active) setFull("none");
      });
    return () => {
      active = false;
    };
  }, [item, open, target.episodeId]);

  const start = async (visibility: Visibility) => {
    if (busy) return;
    setBusy(true);
    setProblem(null);
    try {
      const made = await api.publishProgramme(target.id, visibility);
      setItem(made);
      setRevoked(false);
      if (made.status === "preparing" || made.status === "mixing") watchPublication({ programmeId: target.id, title: target.title });
    } catch (error) {
      setProblem(problemFor(error));
    } finally {
      setBusy(false);
    }
  };

  const change = async (visibility: Visibility, current: PublicationItem) => {
    setItem({ ...current, visibility });
    try {
      setItem(await api.setPublicationVisibility(current.id, visibility));
    } catch {
      setItem(current);
    }
  };

  const withdraw = async (current: PublicationItem) => {
    if (busy) return;
    setBusy(true);
    try {
      setItem(await api.revokePublication(current.id));
      unwatchPublication(target.id);
      setRevoked(true);
    } catch {
      setProblem({ title: "没有撤回成功", body: "过一会儿再试一次。", primary: "知道了" });
    } finally {
      setBusy(false);
    }
  };

  const loading = item === undefined || (item === null && Boolean(target.episodeId) && full === null);
  const wholeAlready = full === "ready" || item?.status === "revoked";
  const frameProps = { open, onClose, target, url };

  if (problem) {
    return (
      <Frame {...frameProps}>
        <div className="ss-message">
          <h3>{problem.title}</h3>
          <p>{problem.body}</p>
        </div>
        <div className="ss-actions">
          {problem.toLibrary ? (
            <a className="pill-button ss-primary" href="/library" onClick={onClose}>{problem.primary}</a>
          ) : (
            <button type="button" className="pill-button ss-primary" onClick={() => { setProblem(null); if (!problem.secondary) onClose(); }}>{problem.primary}</button>
          )}
          {problem.secondary ? <button type="button" className="pill-button ss-secondary" onClick={onClose}>{problem.secondary}</button> : null}
        </div>
      </Frame>
    );
  }

  if (loading) {
    return <Frame {...frameProps}><div className="ss-skeleton" aria-busy="true" /></Frame>;
  }

  if (item && isBeingMade(item)) {
    const steps = [
      { name: "准备完整版", state: item.step === "full" ? "active" : "done", pct: item.step === "full" ? item.progress : 100 },
      { name: "合成分享音频", state: item.step === "mix" ? "active" : "wait", pct: item.step === "mix" ? item.progress : 0 },
    ] as const;
    return (
      <Frame {...frameProps}>
        <ol className="ss-steps" aria-label="发布进度">
          {steps.map((step) => (
            <li key={step.name} className={`ss-step is-${step.state}`}>
              {step.state === "done" ? (
                <span className="ss-step-mark is-done" aria-label="已完成"><CheckIcon size={16} strokeWidth={3} /></span>
              ) : step.state === "active" && step.name === "合成分享音频" ? (
                // One pass whose progress is not known: a spinner and the usual time, not a made-up number.
                <span className="ss-step-mark is-spin" role="img" aria-label="合成中" />
              ) : step.state === "active" ? (
                <span className="ss-step-mark is-ring" role="img" aria-label={`进行中 ${step.pct}%`} style={{ background: `conic-gradient(var(--live) ${step.pct}%, rgba(29,29,31,.1) 0)` }}><span /></span>
              ) : (
                <span className="ss-step-mark is-wait" aria-label="等待" />
              )}
              <span className="ss-step-text">
                <span className="ss-step-name">{step.name}</span>
                <span className="ss-step-hint">
                  {step.state === "done"
                    ? "已完成"
                    : step.state === "active"
                      ? step.name === "准备完整版" ? `准备中 ${step.pct}%` : "合成中，一般 1–2 分钟"
                      : "等上一步做完"}
                </span>
              </span>
            </li>
          ))}
        </ol>
        <div className="ss-actions">
          <button type="button" className="pill-button ss-secondary" onClick={onClose}>先关闭</button>
        </div>
        <p className="ss-note" role="status">做好会提醒你，链接也会留在这里。</p>
      </Frame>
    );
  }

  if (item?.status === "published") {
    return (
      <Frame {...frameProps}>
        <div className="ss-vis">
          <span className="ss-label">谁能听</span>
          <Segmented
            kind="tab"
            label="谁能听"
            options={(["link", "public"] as const).map((value) => ({ value, label: VISIBILITY_LABEL[value] }))}
            value={item.visibility}
            onChange={(value) => void change(value, item)}
          />
          <span className="ss-hint">{VISIBILITY_HINT[item.visibility]}</span>
        </div>
        <LinkActions url={url ?? ""} title={target.title} copied={copied} native={native} copy={copy} />
        <button type="button" className="ss-revoke" disabled={busy} onClick={() => void withdraw(item)}>撤回分享</button>
        <p className={failed ? "ss-note is-error" : "ss-note"} role="status">
          {failed ? "这台设备没让我们复制，可以长按上面的地址自己复制。" : "撤回后，新的人打不开链接；已经加进节目库的，还能继续听。"}
        </p>
      </Frame>
    );
  }

  if (item?.status === "failed") {
    return (
      <Frame {...frameProps}>
        <div className="ss-message">
          <h3>合成没成功</h3>
          <p>已经做好的部分不用重做，再试一次就好。</p>
        </div>
        <div className="ss-actions">
          <button type="button" className="pill-button ss-primary" disabled={busy} onClick={() => void start(item.visibility)}>重试</button>
          <button type="button" className="pill-button ss-secondary" onClick={onClose}>先关闭</button>
        </div>
      </Frame>
    );
  }

  if (!wholeAlready) {
    return (
      <Frame {...frameProps}>
        <div className="ss-message">
          <h3>节目还没准备完整，需要准备好完整版吗？</h3>
          <p>别人听到的是整档节目，要先做完才能打开链接。</p>
        </div>
        <div className="ss-actions">
          <button type="button" className="pill-button ss-primary" disabled={busy} onClick={() => void start("link")}>准备完整版</button>
          <button type="button" className="pill-button ss-secondary" onClick={onClose}>先不了</button>
        </div>
        <p className="ss-note">做的时候可以离开，做好会提醒你。</p>
      </Frame>
    );
  }

  return (
    <Frame {...frameProps}>
      <div className="ss-vis">
        <span className="ss-label">谁能听</span>
        <ul className="ss-choices">
          {(["link", "public"] as const).map((value) => (
            <li key={value}>
              <button type="button" aria-pressed={choice === value} onClick={() => setChoice(value)}>
                <span>
                  <strong>{VISIBILITY_LABEL[value]}</strong>
                  <small>{value === "link" ? "不会出现在首页" : "也会出现在首页的「大家都在听」"}</small>
                </span>
                {choice === value ? <CheckIcon size={22} strokeWidth={2.4} aria-label="已选" /> : null}
              </button>
            </li>
          ))}
        </ul>
      </div>
      <div className="ss-actions">
        <button type="button" className="pill-button ss-primary" disabled={busy} onClick={() => void start(choice)}>
          {revoked || item?.status === "revoked" ? "重新分享" : "发布"}
        </button>
      </div>
      <p className="ss-note">{revoked ? "已撤回，新的人打不开链接。" : "别人听的是同一份音频，不用再生成，也不占你的次数。"}</p>
    </Frame>
  );
}
