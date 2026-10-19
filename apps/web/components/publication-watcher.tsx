"use client";

import { useEffect, useState } from "react";

import {
  PUBLICATION_POLL_MS,
  pollWatchedPublications,
  readWatchedPublications,
  subscribePublications,
  type FinishedPublication,
} from "../lib/publications";
import { copyText, publishedShareUrl } from "../lib/share";
import { stationForProgramme } from "../lib/stations";
import { ProgrammeCoverView } from "./cover/programme-cover-view";

const BANNER_MS = 8000;

/**
 * Keeps an eye on the programmes this device is publishing (nothing runs while there are none) and,
 * when one can be shared, says so with a banner over whatever page the listener is on. Hidden over
 * the player, which has its own sheet for it.
 */
export function PublicationWatcher({ hidden }: { hidden: boolean }) {
  const [pending, setPending] = useState(false);
  const [banner, setBanner] = useState<FinishedPublication | null>(null);

  useEffect(() => {
    const refresh = () => setPending(readWatchedPublications().length > 0);
    refresh();
    return subscribePublications(refresh);
  }, []);

  useEffect(() => {
    if (!pending) return;
    let active = true;
    const poll = async () => {
      if (document.visibilityState === "hidden") return;
      const finished = await pollWatchedPublications();
      if (active && finished.length) setBanner(finished[0]);
    };
    void poll();
    const timer = window.setInterval(() => void poll(), PUBLICATION_POLL_MS);
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

  if (hidden || !banner) return null;
  return <FinishedBanner banner={banner} onDone={() => setBanner(null)} />;
}

function FinishedBanner({ banner, onDone }: { banner: FinishedPublication; onDone: () => void }) {
  const [copied, setCopied] = useState(false);
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
        <small>分享链接准备好了</small>
      </span>
      <button
        type="button"
        onClick={() => {
          void copyText(publishedShareUrl(banner.item.id, banner.programmeId)).then((done) => {
            setCopied(done);
            window.setTimeout(onDone, done ? 1400 : 0);
          });
        }}
      >
        {copied ? "已复制" : "去复制"}
      </button>
    </div>
  );
}
