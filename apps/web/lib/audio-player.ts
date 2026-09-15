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
  options: { sourceUrl: string | null; positionSeconds: number; playing: boolean },
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
  } else if (Math.abs(audio.currentTime - options.positionSeconds) > 1) {
    audio.currentTime = Math.max(0, options.positionSeconds);
  }

  if (options.playing && audio.src) {
    if (audio.paused) void Promise.resolve(audio.play()).catch(() => undefined);
  } else if (!options.playing && !audio.paused) {
    audio.pause();
  }
}
