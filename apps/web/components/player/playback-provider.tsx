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
import { markProgrammeFinished } from "../../lib/install";
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
    setTarget((previous) => (
      only && targetKey(previous) !== targetKey(only) ? previous : null
    ));
  }, []);
  const reload = useCallback(() => setAttempt((value) => value + 1), []);
  const control = useMemo(() => ({ open, close, reload }), [close, open, reload]);
  const [store] = useState(createNowPlayingStore);

  return (
    <ControlContext.Provider value={control}>
      <StoreContext.Provider value={store}>
        {children}
        <PlaybackHost key={targetKey(target) + "#" + attempt} target={target ?? {}} hostEpisodeRef={hostEpisodeRef} store={store} />
      </StoreContext.Provider>
    </ControlContext.Provider>
  );
}

function PlaybackHost({
  target,
  hostEpisodeRef,
  store,
}: {
  target: ProgrammePlaybackTarget;
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
          playing={playback.browserPlaying && episode.is_listener_active}
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
          }}
          onFrontierReached={playback.handleFrontierReached}
          onPlayRequest={playback.resumePlayback}
          onPauseRequest={playback.pausePlayback}
          onSeekRequest={playback.commitSeek}
          onError={(message) => playback.setError(message)}
        />
      ) : null}
    </>
  );
}
