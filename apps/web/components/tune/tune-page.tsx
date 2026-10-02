"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "../../lib/api";
import { isPlaybackReadySegment } from "../../lib/playback";
import {
  DURATIONS,
  FREQ_MAX,
  FREQ_MIN,
  formatFreq,
  matchStation,
  rememberProgrammeStation,
  stationById,
  STATIONS,
  type Station,
} from "../../lib/stations";
import { friendlyError } from "../../lib/friendly-error";
import { readLocalTaste, tasteContext } from "../../lib/taste";
import {
  clampFreq,
  freqAfterDrag,
  knurlPath,
  knurlPhaseForFreq,
  PX_PER_MHZ,
  readTuner,
  stepStation,
} from "../../lib/tuner";
import type { DurationIntent, ProgramProposal } from "../../lib/types";
import { recordCreatedProgram } from "../../lib/user-library";
import { AppShell } from "../app-shell";
import { Segmented } from "../segmented";
import { useNowPlaying, usePlaybackControl } from "../player/playback-provider";
import { useImmersiveOverlay } from "../../lib/chrome-visibility";
import { easeStandard, prefersReducedMotion, tween } from "../../lib/motion/easing";
import { VelocityTracker } from "../../lib/motion/gesture";
import { animateSpring, type Cancel } from "../../lib/motion/spring";
import { openPlayer } from "../../lib/player-nav";
import { TuningInScreen, type TuningStep } from "./tuning-in";
import { TuningWindow, useElementWidth } from "./tuning-window";

const LAST_STATION_KEY = "wavecast-last-station-v1";
const MATCH_SLIDE_MS = 500;

/** Inertia: velocity decays to 0.998× per ms (iOS normal scrolling). */
const GLIDE_DECAY_PER_MS = 0.998;
/** Below this speed (px/ms) the glide hands over to the snapping spring. */
const GLIDE_STOP_SPEED = 0.05;

type Phase =
  | { kind: "idle" }
  | { kind: "tuning"; station: Station; label: string; proposal: ProgramProposal | null; error: string | null };

export function TunePage() {
  const router = useRouter();
  const { open, close, reload } = usePlaybackControl();
  const np = useNowPlaying();

  const [freq, setFreqState] = useState(STATIONS[0].freq);
  const freqRef = useRef(freq);
  const [dragging, setDragging] = useState(false);
  const [text, setText] = useState("");
  const [matched, setMatched] = useState(false);
  const manualRef = useRef(false);
  const [duration, setDuration] = useState<DurationIntent>("STANDARD");
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const requestRef = useRef(0);
  const animRef = useRef<Cancel | null>(null);
  const lastLockedRef = useRef<string | null>(null);
  const { ref: windowRef, width } = useElementWidth<HTMLDivElement>();

  const setFreq = useCallback((value: number) => {
    const next = clampFreq(value);
    freqRef.current = next;
    setFreqState(next);
  }, []);

  const stopAnimation = useCallback(() => {
    animRef.current?.();
    animRef.current = null;
  }, []);

  /** Slide the scale to a station (match, tap, keyboard, home card): 500ms ease-standard. */
  const animateTo = useCallback((target: number, durationMs = MATCH_SLIDE_MS) => {
    stopAnimation();
    if (prefersReducedMotion()) {
      setFreq(target);
      return;
    }
    animRef.current = tween({
      from: freqRef.current,
      to: target,
      duration: durationMs,
      easing: easeStandard,
      onUpdate: setFreq,
      onComplete: () => { animRef.current = null; },
    });
  }, [setFreq, stopAnimation]);

  /** Spring onto the nearest station, carrying the release velocity (px/ms). */
  const snapWithSpring = useCallback((velocityPx: number) => {
    stopAnimation();
    const target = readTuner(freqRef.current).station.freq;
    if (prefersReducedMotion()) {
      setFreq(target);
      return;
    }
    animRef.current = animateSpring({
      from: freqRef.current * PX_PER_MHZ,
      to: target * PX_PER_MHZ,
      velocity: velocityPx,
      epsilon: 0.2,
      onUpdate: (px) => setFreq(px / PX_PER_MHZ),
      onComplete: () => { animRef.current = null; },
    });
  }, [setFreq, stopAnimation]);

  /** Inertial glide, then spring snap once slower than GLIDE_STOP_SPEED. */
  const glide = useCallback((initialVelocityPx: number) => {
    stopAnimation();
    let velocity = initialVelocityPx;
    let last = performance.now();
    let frame = requestAnimationFrame(function step(now) {
      const dt = Math.min(64, now - last);
      last = now;
      const decayed = velocity * Math.pow(GLIDE_DECAY_PER_MS, dt);
      // Distance covered while decaying exponentially over dt.
      const travel = (velocity - decayed) / -Math.log(GLIDE_DECAY_PER_MS);
      velocity = decayed;
      const next = clampFreq(freqRef.current + travel / PX_PER_MHZ);
      setFreq(next);
      const atEdge = next <= FREQ_MIN || next >= FREQ_MAX;
      if (Math.abs(velocity) < GLIDE_STOP_SPEED || atEdge) {
        animRef.current = null;
        snapWithSpring(atEdge ? 0 : velocity);
        return;
      }
      frame = requestAnimationFrame(step);
    });
    animRef.current = () => cancelAnimationFrame(frame);
  }, [setFreq, snapWithSpring, stopAnimation]);

  // Initial station: ?station= from a home card, else the last one tuned.
  useEffect(() => {
    let fromQuery: Station | null = null;
    let last: Station | null = null;
    try {
      const id = new URLSearchParams(window.location.search).get("station");
      fromQuery = id ? stationById(id) : null;
      if (fromQuery) manualRef.current = true;
      const lastId = window.localStorage.getItem(LAST_STATION_KEY);
      last = lastId ? stationById(lastId) : null;
    } catch {
      fromQuery = null;
    }
    if (last) setFreq(last.freq);
    // From a home station card: slide from where the dial was to that station.
    if (fromQuery && Math.abs(fromQuery.freq - freqRef.current) > 0.01) animateTo(fromQuery.freq);
    return stopAnimation;
  }, [animateTo, setFreq, stopAnimation]);

  useImmersiveOverlay("tuning-in", phase.kind === "tuning");

  const reading = readTuner(freq);
  const station = reading.station;
  const between = reading.between;

  // Light haptic tick when a station locks in (Android; iOS web ignores it).
  useEffect(() => {
    if (reading.locked && lastLockedRef.current !== station.id) {
      lastLockedRef.current = station.id;
      try {
        navigator.vibrate?.(8);
      } catch {
        // Unsupported.
      }
    } else if (!reading.locked) {
      lastLockedRef.current = null;
    }
  }, [reading.locked, station.id]);

  // Free text -> station matching, until the listener tunes by hand.
  useEffect(() => {
    if (!text.trim()) {
      manualRef.current = false;
      setMatched(false);
      return;
    }
    if (manualRef.current) return;
    const timer = window.setTimeout(() => {
      const target = stationById(matchStation(text));
      setMatched(true);
      if (Math.abs(target.freq - freqRef.current) > 0.01) animateTo(target.freq);
    }, 350);
    return () => window.clearTimeout(timer);
  }, [animateTo, text]);

  // --- Drag with inertia, then snap to the nearest station.
  const dragState = useRef<{ x: number; freq: number; tracker: VelocityTracker; label: string | null; moved: boolean } | null>(null);

  const markManual = () => {
    manualRef.current = true;
    setMatched(false);
  };

  const onPointerDown = (event: React.PointerEvent<HTMLElement>) => {
    if (event.button !== 0 && event.pointerType === "mouse") return;
    stopAnimation();
    event.currentTarget.setPointerCapture(event.pointerId);
    const label = (event.target as HTMLElement).closest?.("[data-station]")?.getAttribute("data-station") ?? null;
    const tracker = new VelocityTracker();
    tracker.reset(performance.now(), freqRef.current * PX_PER_MHZ);
    dragState.current = { x: event.clientX, freq: freqRef.current, tracker, label, moved: false };
    setDragging(true);
  };

  const onPointerMove = (event: React.PointerEvent<HTMLElement>) => {
    const drag = dragState.current;
    if (!drag) return;
    const dx = event.clientX - drag.x;
    if (Math.abs(dx) > 4) {
      drag.moved = true;
      markManual();
    }
    const next = freqAfterDrag(drag.freq, dx);
    setFreq(next);
    drag.tracker.add(performance.now(), next * PX_PER_MHZ);
  };

  const onPointerUp = () => {
    const drag = dragState.current;
    dragState.current = null;
    setDragging(false);
    if (!drag) return;
    if (!drag.moved && drag.label) {
      // A tap on a station name tunes straight to it.
      tapStation(stationById(drag.label));
      return;
    }
    // Velocity over the last 80ms, in px/ms of scale travel.
    const velocity = drag.tracker.velocity(performance.now());
    if (prefersReducedMotion()) {
      snapWithSpring(0);
      return;
    }
    if (Math.abs(velocity) < GLIDE_STOP_SPEED) snapWithSpring(velocity);
    else glide(velocity);
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    markManual();
    animateTo(stepStation(freqRef.current, event.key === "ArrowRight" ? 1 : -1).freq);
  };

  const tapStation = (target: Station) => {
    markManual();
    animateTo(target.freq);
  };

  // --- Start: proposal -> play immediately, with the tuning-in screen meanwhile.
  const start = useCallback(async (target: Station, prompt: string) => {
    const requestId = requestRef.current + 1;
    requestRef.current = requestId;
    const label = prompt.trim() || target.name;
    setPhase({ kind: "tuning", station: target, label, proposal: null, error: null });
    try {
      window.localStorage.setItem(LAST_STATION_KEY, target.id);
    } catch {
      // Ignore.
    }
    try {
      const batch = await api.createProgramProposals({
        prompt: prompt.trim().length >= 2 ? prompt.trim() : target.defaultTopic,
        duration_intent: duration,
        count: 1,
        taste_context: tasteContext(readLocalTaste()),
      });
      if (requestRef.current !== requestId) return;
      const proposal = batch.proposals[0];
      if (!proposal) throw new Error("没有拿到节目方案");
      rememberProgrammeStation(proposal.id, target.id);
      recordCreatedProgram(proposal.id);
      setPhase({ kind: "tuning", station: target, label, proposal, error: null });
      open({ seedId: proposal.id });
    } catch (reason: unknown) {
      if (requestRef.current !== requestId) return;
      setPhase({
        kind: "tuning",
        station: target,
        label,
        proposal: null,
        error: reason instanceof Error && /[一-鿿]/.test(reason.message) ? reason.message : "开播失败了，可以再试一次",
      });
    }
  }, [duration, open]);

  const tuningProposalId = phase.kind === "tuning" ? phase.proposal?.id ?? null : null;
  const hostEpisode = np?.localEpisode && tuningProposalId && np.localEpisode.seed_id === tuningProposalId
    ? np.localEpisode
    : null;
  const opening = useMemo(
    () => hostEpisode
      ? [...hostEpisode.segments].sort((a, b) => a.order - b.order).find((segment) => segment.kind === "MUSIC")
      : undefined,
    [hostEpisode],
  );
  const audioReady = Boolean(
    hostEpisode
    && np?.programManifest
    && np.programManifest.chunks.length > 0
    && np.programManifest.renderedFrontierSeconds > 0,
  );

  // First playable audio -> go to the player.
  useEffect(() => {
    if (audioReady && hostEpisode) {
      requestRef.current += 1;
      // 开播中 cross-fades into the player (MOTION.md §4.8).
      openPlayer(`/episode/materialized/${hostEpisode.id}`, "fade");
    }
  }, [audioReady, hostEpisode, router]);

  const cancel = () => {
    requestRef.current += 1;
    if (tuningProposalId) {
      // open() may already have been called even if the episode has not
      // loaded yet: always unload this programme so a late start cannot play.
      if (hostEpisode && np) np.leaveEpisode();
      close({ seedId: tuningProposalId });
    }
    setPhase({ kind: "idle" });
  };

  const tuningError = phase.kind === "tuning"
    ? phase.error ?? (hostEpisode && np?.renderState === "error" ? "节目音频暂时没有准备好" : null)
      ?? (tuningProposalId && np?.target.seedId === tuningProposalId && !hostEpisode && np.error ? friendlyError(np.error, "节目暂时无法开始，可以再试一次") : null)
    : null;

  const retry = () => {
    if (phase.kind !== "tuning") return;
    if (hostEpisode && np) {
      np.requestProgramRender();
      return;
    }
    if (phase.proposal) {
      // The proposal exists; only the episode start failed. Retry that.
      reload();
      return;
    }
    void start(phase.station, text);
  };

  const steps: TuningStep[] = phase.kind === "tuning" ? [
    { label: phase.proposal ? `听懂了：${phase.label}` : "正在理解你想听的", done: Boolean(phase.proposal) },
    {
      label: opening && isPlaybackReadySegment(opening)
        ? `开场歌就位：${opening.artist ? opening.artist : ""}《${opening.title}》`
        : "正在找开场歌",
      done: Boolean(opening && isPlaybackReadySegment(opening)),
    },
    { label: "正在排后面的曲目", done: audioReady },
  ] : [];

  const glowColor = between ? "#B8B8C0" : station.light;
  const cta = between ? "先对准一个台" : `在 FM ${formatFreq(station.freq)} 开播`;

  return (
    <AppShell
      fixed
      background={(
        <>
          <span className="glow tune-glow" aria-hidden="true" style={{ left: -90, top: -140, width: 460, height: 420, background: glowColor, opacity: between ? 0.22 : 0.32 }} />
          <span className="glow" aria-hidden="true" style={{ right: -120, top: 140, width: 260, height: 260, background: "#E8834A", opacity: 0.12, filter: "blur(70px)" }} />
        </>
      )}
    >
      <div className="tune">
        <h1 className="page-title">调频</h1>

        <section className="tuner-card" aria-label="调谐">
          <div className="tuner-readout">
            <div className="tuner-freq">
              <span className="tuner-fm">FM</span>
              <span className="tuner-number tabular">{formatFreq(freq)}</span>
            </div>
            <span className="signal" role="img" aria-label={reading.locked ? "信号满格" : between ? "信号弱" : "信号一般"}>
              {[6, 9, 12, 15, 18].map((h, index) => {
                const lit = index < reading.bars;
                // Bars light up left-to-right and go out right-to-left, 250ms in total.
                const delay = (lit ? index : 4 - index) * 50;
                return <span key={h} style={{ height: h, transitionDelay: `${delay}ms` }} className={lit ? "is-lit" : undefined} />;
              })}
            </span>
          </div>

          <div className="tuner-station">
            <div className="tuner-name-row">
              <span key={between ? "between" : station.id} className={between ? "tuner-name is-between" : "tuner-name"}>
                {between ? "两个台之间" : station.name}
              </span>
              {matched && !between ? <span className="match-badge" style={{ background: station.light + "2E", color: station.deep }}>按描述对准</span> : null}
            </div>
            <p>{between ? "松手会自动对准最近的台" : station.description}</p>
          </div>

          <div
            ref={windowRef}
            className={dragging ? "tuning-window is-dragging" : "tuning-window"}
            role="slider"
            tabIndex={0}
            aria-label="调频"
            aria-valuemin={87.5}
            aria-valuemax={108}
            aria-valuenow={Number(formatFreq(freq))}
            aria-valuetext={between ? `FM ${formatFreq(freq)}，没有电台` : `FM ${formatFreq(freq)} ${station.name}`}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
            onKeyDown={onKeyDown}
          >
            <TuningWindow
              freq={freq}
              width={width}
              activeStation={reading.locked ? station : null}
              noise={reading.noise}
            />
          </div>

          <div
            className="knurl"
            aria-hidden="true"
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
          >
            <svg width={width} height={26} viewBox={`0 0 ${width} 26`}>
              <path d={knurlPath(width, knurlPhaseForFreq(freq, width))} />
            </svg>
          </div>
        </section>

        <label className="tune-input">
          <span className="visually-hidden">想听什么</span>
          <input
            type="text"
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder="说一个歌手、一首歌，或者你在做什么"
            enterKeyHint="go"
            maxLength={200}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !between) void start(station, text);
            }}
          />
        </label>

        <Segmented
          label="时长"
          options={DURATIONS}
          value={duration}
          onChange={setDuration}
        />

        <button type="button" className="on-air" disabled={between} onClick={() => void start(station, text)}>
          <span className="on-air-light" aria-hidden="true" />
          {cta}
        </button>
      </div>

      {phase.kind === "tuning" ? (
        <TuningInScreen
          station={phase.station}
          steps={steps}
          error={tuningError}
          onCancel={cancel}
          onRetry={retry}
        />
      ) : null}
    </AppShell>
  );
}
