import { clampMixPosition, evaluateGain, scheduleAt, type MixClip, type MixPlan } from "./mix-timeline";

type MediaElement = HTMLAudioElement;

type EngineEntry = {
  clip: MixClip;
  audio: MediaElement;
  gainNode: GainNode;
};

export type MixEngineOptions = {
  onPositionChange: (positionSeconds: number) => void;
  onEnded: () => void;
  onError?: () => void;
  audioContextFactory?: () => AudioContext;
  clock?: () => number;
};

function defaultAudioContext(): AudioContext {
  const Context = window.AudioContext
    ?? (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!Context) throw new Error("Web Audio API is unavailable");
  return new Context();
}

export class MixEngine {
  private readonly context: AudioContext;
  private readonly options: MixEngineOptions;
  private entries: EngineEntry[] = [];
  private plan: MixPlan | null = null;
  private positionSeconds = 0;
  private lastClockSeconds = 0;
  private lastEmittedPositionSeconds: number | null = null;
  private timer: number | null = null;
  private playing = false;

  constructor(options: MixEngineOptions) {
    this.options = options;
    this.context = (options.audioContextFactory ?? defaultAudioContext)();
  }

  setPlan(plan: MixPlan): void {
    this.stopSources();
    for (const entry of this.entries) entry.audio.remove();
    this.entries = plan.clips.map((clip) => {
      const audio = new Audio(clip.sourceUrl);
      audio.preload = "auto";
      audio.crossOrigin = "anonymous";
      audio.addEventListener("error", () => this.options.onError?.());
      const gainNode = this.context.createGain();
      this.context.createMediaElementSource(audio).connect(gainNode).connect(this.context.destination);
      return { clip, audio, gainNode };
    });
    this.plan = plan;
    this.positionSeconds = 0;
    this.lastEmittedPositionSeconds = null;
    this.lastClockSeconds = this.nowSeconds();
  }

  sync(positionSeconds: number, playing: boolean): void {
    if (!this.plan) return;
    const nextPositionSeconds = clampMixPosition(this.plan, positionSeconds);
    if (
      this.lastEmittedPositionSeconds !== null
      && playing
      && this.playing
      && Math.abs(this.lastEmittedPositionSeconds - nextPositionSeconds) < 0.001
    ) {
      this.lastEmittedPositionSeconds = null;
      return;
    }
    this.lastEmittedPositionSeconds = null;
    this.positionSeconds = nextPositionSeconds;
    this.lastClockSeconds = this.nowSeconds();
    this.playing = playing;
    if (playing) {
      void this.context.resume();
      this.startTimer();
    } else {
      this.stopTimer();
    }
    this.syncSources();
  }

  dispose(): void {
    this.stopTimer();
    this.stopSources();
    for (const entry of this.entries) entry.audio.remove();
    this.entries = [];
    void this.context.close();
  }

  private nowSeconds(): number {
    return (this.options.clock ?? (() => (
      typeof performance === "undefined" ? Date.now() / 1000 : performance.now() / 1000
    )))();
  }

  private startTimer(): void {
    if (this.timer !== null) return;
    this.timer = window.setInterval(() => this.tick(), 100);
  }

  private stopTimer(): void {
    if (this.timer === null) return;
    window.clearInterval(this.timer);
    this.timer = null;
  }

  private tick(): void {
    if (!this.plan || !this.playing) return;
    const now = this.nowSeconds();
    this.positionSeconds = clampMixPosition(
      this.plan,
      this.positionSeconds + Math.max(0, now - this.lastClockSeconds),
    );
    this.lastClockSeconds = now;
    this.syncSources();
    this.lastEmittedPositionSeconds = this.positionSeconds;
    this.options.onPositionChange(this.positionSeconds);
    if (this.positionSeconds >= this.plan.durationSeconds) {
      this.playing = false;
      this.stopTimer();
      this.stopSources();
      this.options.onEnded();
    }
  }

  private stopSources(): void {
    for (const entry of this.entries) {
      entry.audio.pause();
      entry.audio.currentTime = 0;
    }
  }

  private syncSources(): void {
    if (!this.plan) return;
    const scheduled = new Map(scheduleAt(this.plan, this.positionSeconds).map((item) => [item.clip.id, item]));
    for (const entry of this.entries) {
      const item = scheduled.get(entry.clip.id);
      if (!item) {
        entry.audio.pause();
        continue;
      }
      entry.gainNode.gain.value = evaluateGain(entry.clip, this.positionSeconds);
      const drift = Math.abs(entry.audio.currentTime - item.sourceTimeSeconds);
      if (drift > 0.2 || entry.audio.paused) entry.audio.currentTime = item.sourceTimeSeconds;
      if (this.playing) {
        void entry.audio.play().catch(() => undefined);
      } else {
        entry.audio.pause();
      }
    }
  }
}
