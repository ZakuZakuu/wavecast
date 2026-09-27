export type TransportSafeArrangement = {
  sourceOffsetSeconds: number;
  playableDurationSeconds: number;
  fadeInSeconds: number;
  fadeOutSeconds: number;
};

const MAX_TRANSPORT_SAFE_EDGE_FADE_SECONDS = 0.15;

export function transportSafeGain(
  arrangement: TransportSafeArrangement | null | undefined,
  sourcePositionSeconds: number,
): number {
  if (!arrangement) return 1;
  const local = Math.max(0, sourcePositionSeconds - arrangement.sourceOffsetSeconds);
  const duration = Math.max(0, arrangement.playableDurationSeconds);
  if (duration <= 0 || local >= duration) return 0;

  const fadeIn = Math.min(
    MAX_TRANSPORT_SAFE_EDGE_FADE_SECONDS,
    arrangement.fadeInSeconds,
    duration,
  );
  const fadeOut = Math.min(
    MAX_TRANSPORT_SAFE_EDGE_FADE_SECONDS,
    arrangement.fadeOutSeconds,
    duration,
  );
  let gain = 1;
  if (fadeIn > 0) gain = Math.min(gain, local / fadeIn);
  if (fadeOut > 0) gain = Math.min(gain, (duration - local) / fadeOut);
  return Math.max(0, Math.min(1, gain));
}

export type AudioElementLike = {
  src: string;
  currentTime: number;
  paused: boolean;
  load: () => void;
  play: () => Promise<void> | void;
  pause: () => void;
  addEventListener: (name: string, listener: EventListener) => void;
  removeEventListener: (name: string, listener: EventListener) => void;
};

export type AudioLifecycleHandlers = {
  onTimeUpdate: (positionSeconds: number) => void;
  onEnded: () => void;
  onError?: () => void;
};

export function attachAudioLifecycle(
  audio: AudioElementLike,
  handlers: AudioLifecycleHandlers,
): () => void {
  const timeUpdate = () => handlers.onTimeUpdate(audio.currentTime);
  const ended = () => handlers.onEnded();
  const error = () => handlers.onError?.();
  audio.addEventListener("timeupdate", timeUpdate);
  audio.addEventListener("ended", ended);
  audio.addEventListener("error", error);
  return () => {
    audio.removeEventListener("timeupdate", timeUpdate);
    audio.removeEventListener("ended", ended);
    audio.removeEventListener("error", error);
  };
}

export function syncAudioPlayback(
  audio: AudioElementLike,
  options: {
    sourceUrl: string | null;
    positionSeconds: number;
    playing: boolean;
    syncPosition?: boolean;
  },
): void {
  const requestedSource = options.sourceUrl
    ? (() => {
      try {
        return new URL(options.sourceUrl, window.location.href).href;
      } catch {
        return options.sourceUrl;
      }
    })()
    : "";
  const sourceChanged = audio.src !== requestedSource;
  if (sourceChanged) {
    audio.pause();
    audio.src = requestedSource;
    if (audio.src) {
      audio.load();
      audio.currentTime = Math.max(0, options.positionSeconds);
    }
  } else if (
    options.syncPosition
    && Math.abs(audio.currentTime - options.positionSeconds) > 0.05
  ) {
    audio.currentTime = Math.max(0, options.positionSeconds);
  }

  if (options.playing && audio.src) {
    if (audio.paused) void Promise.resolve(audio.play()).catch(() => undefined);
  } else if (!options.playing && !audio.paused) {
    audio.pause();
  }
}
