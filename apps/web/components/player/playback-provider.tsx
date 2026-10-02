"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import { coverArtworkUrl } from "../../lib/cover/artwork";
import { api } from "../../lib/api";
import { markProgrammeFinished } from "../../lib/install";
import {
  clearNowPlayingSession,
  primePausedProgress,
  readNowPlayingSession,
  restorePosition,
  writeNowPlayingSession,
} from "../../lib/now-playing-session";
import { programmeCover, type ProgrammeCover } from "../../lib/cover/programme-cover";
import { stationForProgramme, type Station } from "../../lib/stations";
import {
  useProgrammePlayback,
  type ProgrammePlayback,
  type ProgrammePlaybackTarget,
} from "../../lib/use-programme-playback";
import { ProgrammeAudioPlayer } from "../programme-audio-player";

export type NowPlaying = ProgrammePlayback & {
  /** The programme this host was asked to play; errors belong to it. */
  target: ProgrammePlaybackTarget;
  station: Station | null;
  cover: ProgrammeCover | null;
};

type Control = {
  /** Select the programme the persistent host should play. */
  open: (target: ProgrammePlaybackTarget) => void;
  /**
   * Unload the current programme (e.g. a cancelled tune-in). With `only`, it
   * closes just that programme and leaves anything else playing.
   */
  close: (only?: ProgrammePlaybackTarget) => void;
  /** Remount the host for the same programme (retry after a failed start). */
  reload: () => void;
};

const ControlContext = createContext<Control | null>(null);

/**
 * The playback host is a sibling of the app tree (so remounting it never
 * remounts pages); it publishes its state here and only consumers re-render.
 */
function createNowPlayingStore() {
  let value: NowPlaying | null = null;
  const listeners = new Set<() => void>();
  return {
    get: () => value,
    set: (next: NowPlaying | null) => {
      if (next === value) return;
      value = next;
      listeners.forEach((listener) => listener());
    },
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}

type NowPlayingStore = ReturnType<typeof createNowPlayingStore>;
const StoreContext = createContext<NowPlayingStore | null>(null);

export function usePlaybackControl(): Control {
  const value = useContext(ControlContext);
  if (!value) throw new Error("usePlaybackControl must be used inside PlaybackProvider");
  return value;
}

const serverSnapshot = () => null;

export function useNowPlaying(): NowPlaying | null {
  const store = useContext(StoreContext);
  if (!store) throw new Error("useNowPlaying must be used inside PlaybackProvider");
  return useSyncExternalStore(store.subscribe, store.get, serverSnapshot);
}

/** Selects a programme for playback when a player route mounts. */
export function usePlaybackTarget(target: ProgrammePlaybackTarget): void {
  const { open } = usePlaybackControl();
  const { seedId, episodeId } = target;
  useEffect(() => {
    if (seedId || episodeId) open({ seedId, episodeId });
  }, [episodeId, open, seedId]);
}

function targetKey(target: ProgrammePlaybackTarget | null): string {
  if (!target) return "idle";
  return target.episodeId ? "episode:" + target.episodeId : "seed:" + target.seedId;
}

/**
 * Keeps one programme playback runtime (and its <audio>) alive across routes,
 * so the mini player can keep playing while the listener browses. The host is
 * keyed by its target: switching programme remounts it, exactly like the
 * previous per-route EpisodePlayer mount.
 */
export function PlaybackProvider({ children }: { children: ReactNode }) {
  const [target, setTarget] = useState<ProgrammePlaybackTarget | null>(null);
  const [attempt, setAttempt] = useState(0);
  // Target key restored from a saved session: that host must boot paused.
  const [restoredKey, setRestoredKey] = useState<string | null>(null);
  const hostEpisodeRef = useRef<{ id: string; seedId: string } | null>(null);

  const open = useCallback((next: ProgrammePlaybackTarget) => {
    setTarget((previous) => {
      const host = hostEpisodeRef.current;
      if (next.episodeId && host?.id === next.episodeId) return previous;
      if (!next.episodeId && next.seedId && previous?.seedId === next.seedId && !previous.episodeId) {
        return previous;
      }
      if (targetKey(previous) === targetKey(next)) return previous;
      return next;
    });
  }, []);

  const close = useCallback((only?: ProgrammePlaybackTarget) => {
    setTarget((previous) => {
      if (only && targetKey(previous) !== targetKey(only)) return previous;
      // A deliberate close ends the session: nothing to restore later.
      clearNowPlayingSession();
      return null;
    });
  }, []);

  const targetRef = useRef(target);
  targetRef.current = target;

  // Restore a session that a reclaimed/reloaded page lost (iOS PWA in the
  // background), paused at its last position. Never auto-plays: the host
  // boots paused because the hook's checkpoint is primed as not playing.
  const restoringRef = useRef(false);
  const restore = useCallback(() => {
    if (restoringRef.current) return;
    const session = readNowPlayingSession();
    if (!session) return;
    restoringRef.current = true;
    const episodeId = session.target.episodeId;
    void api.get(episodeId)
      .then((episode) => {
        const lastActivity = episode.last_activity_at ? Date.parse(episode.last_activity_at) : NaN;
        const position = restorePosition(session, {
          positionSeconds: episode.program_playback_position_seconds ?? 0,
          lastActivityAt: Number.isFinite(lastActivity) ? lastActivity : null,
        });
        // A route that already selected a programme wins.
        if (targetRef.current) return;
        primePausedProgress(episodeId, position);
        setRestoredKey(targetKey({ episodeId }));
        setTarget((previous) => previous ?? { episodeId });
      })
      .catch(() => {
        // Gone or no longer ours: forget it.
        clearNowPlayingSession();
      })
      .finally(() => {
        restoringRef.current = false;
      });
  }, []);

  useEffect(() => {
    restore();
    const onPageShow = (event: PageTransitionEvent) => {
      // Back/forward cache restore: re-check only if nothing is loaded.
      if (event.persisted && !targetRef.current) restore();
    };
    window.addEventListener("pageshow", onPageShow);
    return () => window.removeEventListener("pageshow", onPageShow);
  }, [restore]);
  const reload = useCallback(() => setAttempt((value) => value + 1), []);
  const control = useMemo(() => ({ open, close, reload }), [close, open, reload]);
  const [store] = useState(createNowPlayingStore);

  return (
    <ControlContext.Provider value={control}>
      <StoreContext.Provider value={store}>
        {children}
        <PlaybackHost
          key={targetKey(target) + "#" + attempt}
          target={target ?? {}}
          startPaused={restoredKey !== null && restoredKey === targetKey(target)}
          hostEpisodeRef={hostEpisodeRef}
          store={store}
        />
      </StoreContext.Provider>
    </ControlContext.Provider>
  );
}

function PlaybackHost({
  target,
  startPaused,
  hostEpisodeRef,
  store,
}: {
  target: ProgrammePlaybackTarget;
  /** Restored session: never start audio until the listener taps play. */
  startPaused: boolean;
  hostEpisodeRef: React.MutableRefObject<{ id: string; seedId: string } | null>;
  store: NowPlayingStore;
}) {
  const playback = useProgrammePlayback({ ...target, leaveIfAbandoned: true });
  const episode = playback.localEpisode;
  hostEpisodeRef.current = episode ? { id: episode.id, seedId: episode.seed_id } : null;

  const seedId = episode?.seed_id ?? null;
  const title = episode?.title ?? null;
  const station = useMemo(
    () => seedId ? stationForProgramme(seedId, title) : null,
    [seedId, title],
  );
  const cover = useMemo(
    () => seedId && station
      ? programmeCover({ id: seedId, title: title ?? "WaveCast", stationId: station.id })
      : null,
    [seedId, station, title],
  );

  const [artwork, setArtwork] = useState<string | null>(null);
  useEffect(() => {
    if (!cover) return;
    let active = true;
    let url: string | null = null;
    void coverArtworkUrl(cover.params).then((value) => {
      url = value;
      if (active) setArtwork(value);
      else if (value) URL.revokeObjectURL(value);
    });
    return () => {
      active = false;
      if (url) URL.revokeObjectURL(url);
    };
  }, [cover]);

  const value = useMemo<NowPlaying | null>(
    // Publish as soon as a programme is selected, so a failed start (no
    // episode yet) still reaches the player and the tuning-in screen.
    () => target.seedId || target.episodeId ? { ...playback, target, station, cover } : null,
    [cover, playback, station, target],
  );
  const publishedRef = useRef<NowPlaying | null>(null);
  useLayoutEffect(() => {
    publishedRef.current = value;
    store.set(value);
  });
  // Layout cleanup runs before the replacement host publishes, and only
  // clears what this host published, so a remount never wipes its successor.
  useLayoutEffect(() => () => {
    if (store.get() === publishedRef.current) store.set(null);
  }, [store]);

  usePersistSession(playback, target);

  // A restored host may be told by the server that the listener is still
  // active; hold the audio element paused and settle the runtime into its
  // normal paused state once the episode has loaded.
  const [holdPaused, setHoldPaused] = useState(startPaused);
  const pausePlayback = playback.pausePlayback;
  useLayoutEffect(() => {
    if (!holdPaused || !episode) return;
    pausePlayback();
    setHoldPaused(false);
  }, [episode, holdPaused, pausePlayback]);

  const manifest = playback.programManifest;
  const audioReady = Boolean(
    episode
    && manifest
    && manifest.chunks.length > 0
    && manifest.renderedFrontierSeconds > 0,
  );

  return (
    <>
      {audioReady && episode && manifest ? (
        <ProgrammeAudioPlayer
          streamUrl={manifest.streamUrl}
          playing={playback.browserPlaying && episode.is_listener_active && !holdPaused}
          positionSeconds={playback.browserPosition}
          seekToken={playback.seekToken}
          renderedFrontierSeconds={playback.maxSeekPosition}
          complete={manifest.complete}
          title={playback.mediaTitle}
          artist={playback.mediaArtist}
          artwork={artwork}
          onPositionChange={playback.handleProgramPosition}
          onPlayingChange={playback.handlePlayingChange}
          onBufferingChange={playback.setProgramBuffering}
          onEnded={() => {
            playback.handleProgrammeEnded();
            markProgrammeFinished();
            endedSession(playback.localEpisode?.id ?? null);
          }}
          onFrontierReached={playback.handleFrontierReached}
          onPlayRequest={playback.resumePlayback}
          onPauseRequest={playback.pausePlayback}
          onSeekRequest={playback.commitSeek}
          onNextRequest={playback.nextPlayback}
          onError={(message) => playback.setError(message)}
        />
      ) : null}
    </>
  );
}

const endedEpisodes = new Set<string>();

function endedSession(episodeId: string | null): void {
  if (episodeId) endedEpisodes.add(episodeId);
  clearNowPlayingSession();
}

/**
 * Writes the session on start, every 5s of progress, on play/pause, and when
 * the page is hidden or unloaded. A finished programme is not re-written until
 * it plays again.
 */
function usePersistSession(playback: ProgrammePlayback, target: ProgrammePlaybackTarget): void {
  const episode = playback.localEpisode;
  const latest = useRef({ episodeId: null as string | null, seedId: undefined as string | undefined, position: 0, playing: false });
  latest.current = {
    episodeId: episode?.id ?? null,
    seedId: episode?.seed_id ?? target.seedId,
    position: playback.browserPosition,
    playing: playback.browserPlaying,
  };

  const write = useCallback(() => {
    const { episodeId, seedId, position, playing } = latest.current;
    if (!episodeId) return;
    if (playing) endedEpisodes.delete(episodeId);
    if (endedEpisodes.has(episodeId)) return;
    writeNowPlayingSession({ target: { episodeId, seedId }, positionSeconds: position, playing });
  }, []);

  const bucket = Math.floor(playback.browserPosition / 5);
  useEffect(() => {
    write();
  }, [bucket, episode?.id, playback.browserPlaying, write]);

  useEffect(() => {
    const onHide = () => {
      if (document.visibilityState === "hidden") write();
    };
    document.addEventListener("visibilitychange", onHide);
    window.addEventListener("pagehide", write);
    return () => {
      document.removeEventListener("visibilitychange", onHide);
      window.removeEventListener("pagehide", write);
    };
  }, [write]);
}
