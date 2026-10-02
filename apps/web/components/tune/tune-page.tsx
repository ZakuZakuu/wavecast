"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "../../lib/api";
import { isPlaybackReadySegment } from "../../lib/playback";
import {
  DURATIONS,
  formatFreq,
  matchStation,
  rememberProgrammeStation,
  stationById,
  STATIONS,
  type Station,
} from "../../lib/stations";
import { readLocalTaste, tasteContext } from "../../lib/taste";
import {
  clampFreq,
  freqAfterDrag,
  knurlPath,
  knurlPhaseForFreq,
  readTuner,
  stepStation,
} from "../../lib/tuner";
import type { DurationIntent, ProgramProposal } from "../../lib/types";
import { recordCreatedProgram } from "../../lib/user-library";
import { AppShell } from "../app-shell";
import { useNowPlaying, usePlaybackControl } from "../player/playback-provider";
import { TuningInScreen, type TuningStep } from "./tuning-in";
import { TuningWindow, useElementWidth } from "./tuning-window";

const LAST_STATION_KEY = "wavecast-last-station-v1";
const SNAP_MS = 300;
const MATCH_SLIDE_MS = 500;

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined"
    && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;
}

const easeOut = (t: number) => 1 - Math.pow(1 - t, 3);

type Phase =
  | { kind: "idle" }
  | { kind: "tuning"; station: Station; label: string; proposal: ProgramProposal | null; error: string | null };

export function TunePage() {
  const router = useRouter();
  const { open, close } = usePlaybackControl();
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
  const animRef = useRef<number | null>(null);
  const lastLockedRef = useRef<string | null>(null);
  const { ref: windowRef, width } = useElementWidth<HTMLDivElement>();

  const setFreq = useCallback((value: number) => {
    const next = clampFreq(value);
    freqRef.current = next;
    setFreqState(next);
  }, []);

  const stopAnimation = useCallback(() => {
    if (animRef.current !== null) cancelAnimationFrame(animRef.current);
    animRef.current = null;
  }, []);

  const animateTo = useCallback((target: number, durationMs: number) => {
    stopAnimation();
    if (prefersReducedMotion()) {
      setFreq(target);
      return;
    }
    const from = freqRef.current;
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / durationMs);
      setFreq(from + (target - from) * easeOut(t));
      animRef.current = t < 1 ? requestAnimationFrame(tick) : null;
    };
    animRef.current = requestAnimationFrame(tick);
  }, [setFreq, stopAnimation]);

  // Initial station: ?station= from a home card, else the last one tuned.
  useEffect(() => {
    let initial: Station | null = null;
    try {
      const fromQuery = new URLSearchParams(window.location.search).get("station");
      initial = fromQuery ? stationById(fromQuery) : null;
      if (fromQuery) manualRef.current = true;
      if (!initial) {
        const last = window.localStorage.getItem(LAST_STATION_KEY);
        initial = last ? stationById(last) : null;
      }
    } catch {
      initial = null;
    }
    if (initial) setFreq(initial.freq);
    return stopAnimation;
  }, [setFreq, stopAnimation]);

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
      if (Math.abs(target.freq - freqRef.current) > 0.01) animateTo(target.freq, MATCH_SLIDE_MS);
    }, 350);
    return () => window.clearTimeout(timer);
  }, [animateTo, text]);

  // --- Drag with inertia, then snap to the nearest station.
  const dragState = useRef<{ x: number; freq: number; samples: Array<[number, number]> } | null>(null);

  const markManual = () => {
    manualRef.current = true;
    setMatched(false);
  };

  const onPointerDown = (event: React.PointerEvent<HTMLElement>) => {
    if (event.button !== 0 && event.pointerType === "mouse") return;
    stopAnimation();
    event.currentTarget.setPointerCapture(event.pointerId);
    dragState.current = { x: event.clientX, freq: freqRef.current, samples: [[performance.now(), freqRef.current]] };
    setDragging(true);
  };

  const onPointerMove = (event: React.PointerEvent<HTMLElement>) => {
    const drag = dragState.current;
    if (!drag) return;
    const dx = event.clientX - drag.x;
    if (Math.abs(dx) > 2) markManual();
    const next = freqAfterDrag(drag.freq, dx);
    setFreq(next);
    const now = performance.now();
    drag.samples.push([now, next]);
    while (drag.samples.length > 2 && now - drag.samples[0][0] > 90) drag.samples.shift();
  };

  const onPointerUp = () => {
    const drag = dragState.current;
    dragState.current = null;
    setDragging(false);
    if (!drag) return;
    const [t0, f0] = drag.samples[0];
    const [t1, f1] = drag.samples[drag.samples.length - 1];
    let velocity = t1 > t0 ? (f1 - f0) / (t1 - t0) : 0; // MHz per ms
    if (prefersReducedMotion() || Math.abs(velocity) < 0.0005) {
      animateTo(readTuner(freqRef.current).station.freq, SNAP_MS);
      return;
    }
    let last = performance.now();
    const glide = (now: number) => {
      const dt = now - last;
      last = now;
      velocity *= Math.pow(0.92, dt / 16);
      const next = clampFreq(freqRef.current + velocity * dt);
      setFreq(next);
      if (Math.abs(velocity) < 0.0004 || next <= 87.5 || next >= 108) {
        animRef.current = null;
        animateTo(readTuner(freqRef.current).station.freq, SNAP_MS);
        return;
      }
      animRef.current = requestAnimationFrame(glide);
    };
    animRef.current = requestAnimationFrame(glide);
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    markManual();
    animateTo(stepStation(freqRef.current, event.key === "ArrowRight" ? 1 : -1).freq, SNAP_MS);
  };

  const tapStation = (target: Station) => {
    markManual();
    animateTo(target.freq, MATCH_SLIDE_MS);
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
      router.push(`/episode/materialized/${hostEpisode.id}`);
    }
  }, [audioReady, hostEpisode, router]);

  const cancel = () => {
    requestRef.current += 1;
    if (hostEpisode && np) {
      np.leaveEpisode();
      close();
    }
    setPhase({ kind: "idle" });
  };

  const tuningError = phase.kind === "tuning"
    ? phase.error ?? (hostEpisode && np?.renderState === "error" ? "节目音频暂时没有准备好" : null)
      ?? (np?.error && tuningProposalId && !hostEpisode ? np.error : null)
    : null;

  const retry = () => {
    if (phase.kind !== "tuning") return;
    if (hostEpisode && np) {
      np.requestProgramRender();
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
          <span className="glow" aria-hidden="true" style={{ left: -90, top: -140, width: 460, height: 420, background: glowColor, opacity: between ? 0.22 : 0.32 }} />
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
              {[6, 9, 12, 15, 18].map((h, index) => (
                <span key={h} style={{ height: h }} className={index < reading.bars ? "is-lit" : undefined} />
              ))}
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
              onStationTap={tapStation}
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

        <div className="segmented" role="radiogroup" aria-label="时长">
          {DURATIONS.map((item) => (
            <button
              type="button"
              role="radio"
              key={item.value}
              aria-checked={duration === item.value}
              className={duration === item.value ? "is-selected" : undefined}
              onClick={() => setDuration(item.value)}
            >
              {item.label}
            </button>
          ))}
        </div>

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
