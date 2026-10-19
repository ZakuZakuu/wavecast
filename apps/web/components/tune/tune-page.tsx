"use client";

import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";

import { rgba } from "../../lib/cover/styled/color";
import { prepareFullVersionFromTuner, useFullVersionFailure, useFullVersionStarted, useFullVersionStarting } from "../../lib/full-version-requests";
import { claimVisitPrompt } from "../../lib/login-nudge";
import { openOverlayCount } from "../../lib/overlay-stack";
import { stationExamples, stationPlaceholder } from "../../lib/station-guide";
import { markStationGuideSeen, stationGuideSeen } from "../../lib/station-guide-state";
import { formatFreq, type Station } from "../../lib/stations";
import { useSoftKeyboard } from "../../lib/soft-keyboard";
import type { DurationIntent, HostMode } from "../../lib/types";
import { AppShell } from "../app-shell";
import { CheckIcon, QueuePlusIcon, ShuffleIcon } from "../icons";
import { Guide } from "../guide/guide";
import { StationGuide } from "./station-guide";
import { TuneChoices } from "./tune-choices";
import { TunerCard } from "./tuner-card";
import { TuningInScreen } from "./tuning-in";
import { useTuneStart } from "./use-tune-start";
import { useTuner } from "./use-tuner";

/** Sooner than the first-use guide (lib/guide) tries to start, so that the 电台指南 is the first thing it waits for. */
const AUTO_OPEN_DELAY_MS = 300;
const AUTO_OPEN_RETRY_MS = 400;
const AUTO_OPEN_TRIES = 40;

export function TunePage() {
  const tune = useTuneStart();
  const creating = useFullVersionStarting();
  const started = useFullVersionStarted();
  const failure = useFullVersionFailure();
  useSoftKeyboard();

  const tuner = useTuner();
  const { station } = tuner;
  const [text, setText] = useState("");
  const [duration, setDuration] = useState<DurationIntent>("SHORT");
  /** Set only when the listener touched the host control; null leaves the station's default (and the wording) in charge. */
  const [hostPick, setHostPick] = useState<HostMode | null>(null);
  const host = hostPick ?? station.host;
  const cardRef = useRef<HTMLElement>(null);
  const [guideOpen, setGuideOpen] = useState(false);
  const [guideFirst, setGuideFirst] = useState(false);

  const examples = stationExamples(station.id);

  const openGuide = useCallback((first = false) => {
    setGuideFirst(first);
    setGuideOpen(true);
  }, []);
  const closeGuide = useCallback(() => {
    setGuideOpen(false);
    markStationGuideSeen();
  }, []);

  // The first visit: the guide opens by itself, once nothing else is on screen and this visit's prompt slot is free.
  useEffect(() => {
    if (stationGuideSeen() || !claimVisitPrompt("guide")) return;
    let tries = 0;
    let timer = 0;
    const attempt = () => {
      if (openOverlayCount() > 0 && tries < AUTO_OPEN_TRIES) {
        tries += 1;
        timer = window.setTimeout(attempt, AUTO_OPEN_RETRY_MS);
        return;
      }
      openGuide(true);
    };
    timer = window.setTimeout(attempt, AUTO_OPEN_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [openGuide]);

  const pickHost = (value: HostMode) => setHostPick(value === station.host ? null : value);
  const startFrom = (target: Station) => void tune.start(target, text, duration, undefined, hostPick);

  /** Fill the box with the next example of this station (what the grey placeholder shows comes first). */
  const nextExample = () => {
    const at = examples.indexOf(text);
    setText(examples[(at + 1) % examples.length]);
  };

  const pickScene = (target: Station, scene: string) => {
    tuner.tuneTo(target);
    setText(scene);
    closeGuide();
  };

  // The server's refusal to run a third 完整版 at once: the button greys out and the note says what to wait for.
  const limited = Boolean(failure?.startsWith("最多同时准备"));
  const typed = text.trim().length > 0;
  const cta = typed ? `在 FM ${formatFreq(station.freq)} 开播` : "随便放点";
  const tone = {
    "--deep": station.deep,
    "--deep-text": station.deepText,
    "--box-line": rgba(station.light, 0.7),
    "--box-ring": rgba(station.light, 0.16),
    "--box-shadow": rgba(station.light, 0.16),
    "--chip-bg": rgba(station.light, 0.16),
    "--chip-on": rgba(station.light, 0.32),
  } as CSSProperties;

  return (
    <AppShell
      fixed
      background={(
        <>
          <span className="glow tune-glow" aria-hidden="true" style={{ left: -90, top: -140, width: 460, height: 420, background: station.light, opacity: 0.3 }} />
          <span className="glow tune-glow tune-bottom-glow" aria-hidden="true" style={{ left: 80, bottom: 70, width: 420, height: 300, background: station.light, opacity: 0.2 }} />
        </>
      )}
    >
      <div className={guideOpen ? "tune is-guiding" : "tune"} style={tone}>
        <h1 className="page-title">调频</h1>

        <TunerCard tuner={tuner} cardRef={cardRef} onOpenGuide={() => openGuide(false)} />

        <div className="tune-compose">
          <label className="tune-ask" htmlFor="tune-text">想听什么？</label>
          <div className="tune-box" data-guide="tune-input">
            <textarea
              id="tune-text"
              value={text}
              onChange={(event) => setText(event.target.value)}
              placeholder={stationPlaceholder(station.id)}
              enterKeyHint="go"
              maxLength={200}
              rows={2}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                  event.preventDefault();
                  startFrom(station);
                }
              }}
            />
            <button type="button" className="tune-shuffle" aria-label="换一个示例" onClick={nextExample}>
              <ShuffleIcon size={18} strokeWidth={2} />
            </button>
          </div>
        </div>

        <TuneChoices station={station} duration={duration} onDuration={setDuration} host={host} onHost={pickHost} />

        <div className="tune-actions">
          <button type="button" className="on-air" data-guide="tune-onair" onClick={() => startFrom(station)}>
            <span className="on-air-light" aria-hidden="true" />
            {cta}
          </button>
          <button
            type="button"
            className={creating ? "prepare-round is-busy" : started ? "prepare-round is-done" : limited ? "prepare-round is-limited" : "prepare-round"}
            data-guide="tune-prepare"
            aria-label={creating ? "正在准备完整版" : started ? "已开始准备完整版" : "准备完整版"}
            disabled={creating}
            onClick={() => void prepareFullVersionFromTuner(station, text, duration, hostPick)}
          >
            {creating ? <span className="on-air-spinner" aria-hidden="true" /> : started ? <CheckIcon size={22} strokeWidth={2.6} /> : <QueuePlusIcon size={26} strokeWidth={2.1} />}
          </button>
        </div>
        {failure ? <p className="tune-note" role="alert">{limited ? `${failure}，等一档做好再来` : failure}</p> : null}
      </div>

      <StationGuide tuner={tuner} open={guideOpen} first={guideFirst} originRef={cardRef} onClose={closeGuide} onPick={pickScene} />

      <Guide trigger="tune" />
      {tune.tuning ? (
        <TuningInScreen
          station={tune.tuning}
          steps={tune.steps}
          error={tune.error}
          retryable={tune.retryable}
          onCancel={tune.cancel}
          onRetry={tune.retry}
        />
      ) : null}
    </AppShell>
  );
}
