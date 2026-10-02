"use client";

import { useEffect, useRef } from "react";

import { spaceTogglesPlayback } from "../lib/keyboard";
import { useNowPlaying } from "./player/playback-provider";

/** Space plays/pauses the current programme (never while typing). Esc lives in the overlay stack. */
export function KeyboardShortcuts() {
  const np = useNowPlaying();
  const npRef = useRef(np);
  npRef.current = np;

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!spaceTogglesPlayback(event)) return;
      const playback = npRef.current;
      if (!playback?.localEpisode || !playback.programManifest) return;
      event.preventDefault();
      if (playback.browserPlaying) playback.pausePlayback();
      else playback.resumePlayback();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return null;
}
