"use client";

import { useEffect, useState } from "react";

import {
  FULL_VERSION_POLL_MS,
  pollWatchedFullVersions,
  readUnseenFullVersions,
  readWatchedFullVersions,
  subscribeFullVersions,
  type WatchedFullVersion,
} from "../lib/full-versions";
import { useFullVersionNotice } from "../lib/full-version-requests";
import { openPlayer } from "../lib/player-nav";
import { stationForProgramme } from "../lib/stations";
import { ProgrammeCoverView } from "./cover/programme-cover-view";

const BANNER_MS = 7000;

/** How many 完整版 have finished that the listener has not yet looked at in 节目库. */
export function useUnseenFullVersionCount(): number {
  const [count, setCount] = useState(0);
  useEffect(() => {
    const refresh = () => setCount(readUnseenFullVersions().length);
    refresh();
    return subscribeFullVersions(refresh);
  }, []);
  return count;
}

/**
 * Keeps an eye on the 完整版 this device asked for (nothing runs while there are none) and, when one
 * finishes, says so with a banner over whatever page the listener is on. Hidden over the player, which
 * shows the state itself.
 */
export function FullVersionWatcher({ hidden }: { hidden: boolean }) {
  const [pending, setPending] = useState(false);
  const [banner, setBanner] = useState<WatchedFullVersion | null>(null);

  useEffect(() => {
    const refresh = () => setPending(readWatchedFullVersions().length > 0);
    refresh();
    return subscribeFullVersions(refresh);
  }, []);

  useEffect(() => {
    if (!pending) return;
    let active = true;
    const poll = async () => {
      if (document.visibilityState === "hidden") return;
      const finished = await pollWatchedFullVersions();
      if (active && finished.length) setBanner(finished[0]);
    };
    void poll();
    const timer = window.setInterval(() => void poll(), FULL_VERSION_POLL_MS);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [pending]);

  useEffect(() => {
    if (!banner) return;
    const timer = window.setTimeout(() => setBanner(null), BANNER_MS);
    return () => window.clearTimeout(timer);
  }, [banner]);

  const notice = useFullVersionNotice();
  if (hidden) return null;
  return (
    <>
      {notice ? <div className="undo-toast" role="status"><span>{notice}</span></div> : null}
      {banner ? <FinishedBanner banner={banner} onDone={() => setBanner(null)} /> : null}
    </>
  );
}

function FinishedBanner({ banner, onDone }: { banner: WatchedFullVersion; onDone: () => void }) {
  return (
    <div className="full-banner" role="status">
      <span className="full-banner-cover">
        <ProgrammeCoverView
          id={banner.programmeId}
          title={banner.title}
          stationId={stationForProgramme(banner.programmeId, banner.title).id}
          bare
          radius={0}
        />
      </span>
      <span className="full-banner-copy">
        <strong>{banner.title}</strong>
        <small>完整版已准备好</small>
      </span>
      <button
        type="button"
        onClick={() => {
          onDone();
          openPlayer(`/episode/materialized/${encodeURIComponent(banner.episodeId)}`);
        }}
      >
        去听
      </button>
    </div>
  );
}
