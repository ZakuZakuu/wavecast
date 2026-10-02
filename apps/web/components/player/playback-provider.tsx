"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { coverArtworkUrl } from "../../lib/cover/artwork";
import { programmeCover, type ProgrammeCover } from "../../lib/cover/programme-cover";
import { stationForProgramme, type Station } from "../../lib/stations";
import {
  useProgrammePlayback,
  type ProgrammePlayback,
  type ProgrammePlaybackTarget,
} from "../../lib/use-programme-playback";
import { ProgrammeAudioPlayer } from "../programme-audio-player";

export type NowPlaying = ProgrammePlayback & {
  station: Station | null;
  cover: ProgrammeCover | null;
};

type Control = {
  /** Select the programme the persistent host should play. */
  open: (target: ProgrammePlaybackTarget) => void;
};

const ControlContext = createContext<Control | null>(null);
const NowPlayingContext = createContext<NowPlaying | null>(null);

export function usePlaybackControl(): Control {
  const value = useContext(ControlContext);
  if (!value) throw new Error("usePlaybackControl must be used inside PlaybackProvider");
  return value;
}

export function useNowPlaying(): NowPlaying | null {
  return useContext(NowPlayingContext);
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

  const control = useMemo(() => ({ open }), [open]);

  return (
    <ControlContext.Provider value={control}>
      <PlaybackHost key={targetKey(target)} target={target ?? {}} hostEpisodeRef={hostEpisodeRef}>
        {children}
      </PlaybackHost>
    </ControlContext.Provider>
  );
}

function PlaybackHost({
  target,
  hostEpisodeRef,
  children,
}: {
  target: ProgrammePlaybackTarget;
  hostEpisodeRef: React.MutableRefObject<{ id: string; seedId: string } | null>;
  children: ReactNode;
}) {
  const playback = useProgrammePlayback(target);
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
    () => episode ? { ...playback, station, cover } : null,
    [cover, episode, playback, station],
  );

  const manifest = playback.programManifest;
  const audioReady = Boolean(
    episode
    && manifest
    && manifest.chunks.length > 0
    && manifest.renderedFrontierSeconds > 0,
  );

  return (
    <NowPlayingContext.Provider value={value}>
      {children}
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
          onEnded={playback.handleProgrammeEnded}
          onFrontierReached={playback.handleFrontierReached}
          onPlayRequest={playback.resumePlayback}
          onPauseRequest={playback.pausePlayback}
          onSeekRequest={playback.commitSeek}
          onError={(message) => playback.setError(message)}
        />
      ) : null}
    </NowPlayingContext.Provider>
  );
}
