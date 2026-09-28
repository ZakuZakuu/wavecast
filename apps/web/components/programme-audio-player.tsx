"use client";

import { useEffect, useRef } from "react";

const HLS_MIME = "application/vnd.apple.mpegurl";
const FRONTIER_WAKE_SECONDS = 12;
const FRONTIER_SEEK_EPSILON_SECONDS = 0.05;

type ProgrammeAudioPlayerProps = {
  streamUrl: string;
  playing: boolean;
  positionSeconds: number;
  seekToken: number;
  renderedFrontierSeconds: number;
  complete: boolean;
  title: string;
  artist?: string | null;
  onPositionChange: (positionSeconds: number) => void;
  onPlayingChange?: (playing: boolean) => void;
  onEnded: () => void;
  onFrontierReached: () => void;
  onPlayRequest: () => void;
  onPauseRequest: () => void;
  onSeekRequest: (positionSeconds: number) => void;
  onError: (message: string) => void;
};

function boundedSeekTarget(
  target: number,
  frontier: number,
  complete: boolean,
): number {
  const max = complete
    ? Math.max(0, frontier)
    : Math.max(0, frontier - FRONTIER_SEEK_EPSILON_SECONDS);
  return Math.max(0, Math.min(target, max));
}

function safePlay(audio: HTMLAudioElement): void {
  void audio.play().catch(() => undefined);
}

export function ProgrammeAudioPlayer({
  streamUrl,
  playing,
  positionSeconds,
  seekToken,
  renderedFrontierSeconds,
  complete,
  title,
  artist,
  onPositionChange,
  onPlayingChange,
  onEnded,
  onFrontierReached,
  onPlayRequest,
  onPauseRequest,
  onSeekRequest,
  onError,
}: ProgrammeAudioPlayerProps) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const hlsRef = useRef<import("hls.js").default | null>(null);
  const pendingSeekRef = useRef<number | null>(positionSeconds);
  const desiredPlayingRef = useRef(playing);
  const frontierRef = useRef(renderedFrontierSeconds);
  const completeRef = useRef(complete);
  const lastSeekTokenRef = useRef(seekToken);

  desiredPlayingRef.current = playing;
  frontierRef.current = renderedFrontierSeconds;
  completeRef.current = complete;

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio || !streamUrl) return;

    let cancelled = false;
    let detachNativeListeners: (() => void) | null = null;

    const applyPendingSeek = () => {
      if (cancelled || pendingSeekRef.current === null) return;
      const target = boundedSeekTarget(
        pendingSeekRef.current,
        frontierRef.current,
        completeRef.current,
      );
      try {
        audio.currentTime = target;
        pendingSeekRef.current = null;
      } catch {
        // Metadata/seekable ranges may not be ready yet. Keep the target and
        // retry on the next media readiness event.
      }
    };

    const wakeIfDesired = () => {
      applyPendingSeek();
      if (desiredPlayingRef.current && audio.paused) safePlay(audio);
    };

    const attachNative = () => {
      audio.src = streamUrl;
      audio.load();
      const events = ["loadedmetadata", "durationchange", "canplay", "progress"];
      for (const event of events) audio.addEventListener(event, wakeIfDesired);
      detachNativeListeners = () => {
        for (const event of events) audio.removeEventListener(event, wakeIfDesired);
      };
    };

    if (audio.canPlayType(HLS_MIME)) {
      attachNative();
    } else {
      void import("hls.js")
        .then(({ default: Hls }) => {
          if (cancelled) return;
          if (!Hls.isSupported()) {
            onError("当前浏览器暂时不支持节目流播放");
            return;
          }
          const hls = new Hls({
            enableWorker: true,
            lowLatencyMode: false,
            backBufferLength: 600,
            maxBufferLength: 120,
          });
          hlsRef.current = hls;
          hls.attachMedia(audio);
          hls.on(Hls.Events.MEDIA_ATTACHED, () => {
            if (!cancelled) hls.loadSource(streamUrl);
          });
          hls.on(Hls.Events.MANIFEST_PARSED, wakeIfDesired);
          hls.on(Hls.Events.LEVEL_UPDATED, wakeIfDesired);
          hls.on(Hls.Events.ERROR, (_event, data) => {
            if (cancelled || !data.fatal) return;
            if (data.type === Hls.ErrorTypes.NETWORK_ERROR) {
              hls.startLoad();
              return;
            }
            if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {
              hls.recoverMediaError();
              return;
            }
            onError("节目流暂时无法继续播放");
          });
        })
        .catch(() => {
          if (!cancelled) onError("节目播放器加载失败");
        });
    }

    return () => {
      cancelled = true;
      detachNativeListeners?.();
      hlsRef.current?.destroy();
      hlsRef.current = null;
      audio.pause();
      audio.removeAttribute("src");
      audio.load();
    };
  }, [streamUrl, onError]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    if (lastSeekTokenRef.current === seekToken) return;
    lastSeekTokenRef.current = seekToken;
    const target = boundedSeekTarget(
      positionSeconds,
      renderedFrontierSeconds,
      complete,
    );
    pendingSeekRef.current = target;
    try {
      audio.currentTime = target;
      pendingSeekRef.current = null;
    } catch {
      // Retried by readiness listeners installed with the HLS source.
    }
  }, [
    complete,
    positionSeconds,
    renderedFrontierSeconds,
    seekToken,
  ]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    if (playing) {
      safePlay(audio);
    } else {
      audio.pause();
    }
    if ("mediaSession" in navigator) {
      navigator.mediaSession.playbackState = playing ? "playing" : "paused";
    }
  }, [playing]);

  useEffect(() => {
    if (!("mediaSession" in navigator)) return;
    navigator.mediaSession.metadata = new MediaMetadata({
      title,
      artist: artist || "WaveCast",
      album: "WaveCast",
    });
  }, [artist, title]);

  useEffect(() => {
    if (!("mediaSession" in navigator)) return;
    const mediaSession = navigator.mediaSession;
    mediaSession.setActionHandler("play", onPlayRequest);
    mediaSession.setActionHandler("pause", onPauseRequest);
    mediaSession.setActionHandler("seekbackward", (details) => {
      const audio = audioRef.current;
      if (!audio) return;
      onSeekRequest(Math.max(0, audio.currentTime - (details.seekOffset ?? 15)));
    });
    mediaSession.setActionHandler("seekforward", (details) => {
      const audio = audioRef.current;
      if (!audio) return;
      onSeekRequest(
        Math.min(
          frontierRef.current,
          audio.currentTime + (details.seekOffset ?? 30),
        ),
      );
    });
    mediaSession.setActionHandler("seekto", (details) => {
      if (details.seekTime === undefined) return;
      onSeekRequest(details.seekTime);
    });
    return () => {
      for (const action of [
        "play",
        "pause",
        "seekbackward",
        "seekforward",
        "seekto",
      ] as MediaSessionAction[]) {
        try {
          mediaSession.setActionHandler(action, null);
        } catch {
          // Some browsers expose Media Session with a smaller action set.
        }
      }
    };
  }, [onPauseRequest, onPlayRequest, onSeekRequest]);

  const publishPositionState = (audio: HTMLAudioElement) => {
    if (!("mediaSession" in navigator)) return;
    const duration = frontierRef.current;
    if (!Number.isFinite(duration) || duration <= 0) return;
    try {
      navigator.mediaSession.setPositionState({
        duration,
        playbackRate: audio.playbackRate || 1,
        position: Math.min(Math.max(0, audio.currentTime), duration),
      });
    } catch {
      // System media controls are an enhancement; audio playback stays primary.
    }
  };

  return (
    <audio
      ref={audioRef}
      preload="auto"
      playsInline
      onTimeUpdate={(event) => {
        const audio = event.currentTarget;
        onPositionChange(audio.currentTime);
        publishPositionState(audio);
        if (
          !completeRef.current
          && frontierRef.current - audio.currentTime <= FRONTIER_WAKE_SECONDS
        ) {
          onFrontierReached();
        }
      }}
      onPlaying={() => onPlayingChange?.(true)}
      onPause={() => onPlayingChange?.(false)}
      onWaiting={() => {
        const audio = audioRef.current;
        if (
          audio
          && !completeRef.current
          && frontierRef.current - audio.currentTime <= FRONTIER_WAKE_SECONDS
        ) {
          onFrontierReached();
        }
      }}
      onStalled={onFrontierReached}
      onEnded={() => {
        if (completeRef.current) {
          onEnded();
        } else {
          onFrontierReached();
        }
      }}
      onError={() => onError("节目音频暂时无法播放")}
      aria-hidden="true"
    />
  );
}
