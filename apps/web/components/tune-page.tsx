"use client";

import Link from "next/link";
import { useState } from "react";

import { api } from "../lib/api";
import type { DurationIntent, ProgramProposal } from "../lib/types";
import { recordCreatedProgram } from "../lib/user-library";
import { AppShell } from "./app-shell";
import { ProgramCard } from "./program-card";
import { WaveIcon } from "./wave-icon";

const INSPIRATIONS = ["雨夜爵士", "城市漫游", "Chill 电子", "方大同风格", "周末早晨", "专注工作"];
const DURATIONS: Array<{ label: string; value: DurationIntent }> = [
  { label: "自动", value: "AUTO" },
  { label: "短 · 15–30 分钟", value: "SHORT" },
  { label: "标准 · 30–60 分钟", value: "STANDARD" },
  { label: "深入 · 1 小时+", value: "DEEP" },
];

export function TunePage() {
  const [prompt, setPrompt] = useState("");
  const [duration, setDuration] = useState<DurationIntent>("AUTO");
  const [tuning, setTuning] = useState(false);
  const [result, setResult] = useState<ProgramProposal | null>(null);
  const [error, setError] = useState<string | null>(null);

  const beginTune = async () => {
    const normalizedPrompt = prompt.trim();
    if (tuning || normalizedPrompt.length < 2) return;
    setTuning(true);
    setResult(null);
    setError(null);
    try {
      const batch = await api.createProgramProposals({
        prompt: normalizedPrompt,
        duration_intent: duration,
        count: 1,
      });
      const proposal = batch.proposals[0] ?? null;
      setResult(proposal);
      if (proposal) recordCreatedProgram(proposal.id);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "调频失败，请稍后重试");
    } finally {
      setTuning(false);
    }
  };

  return (
    <AppShell>
      <div className="page-header">
        <div><p className="program-kicker">CREATE A STATION</p><h1>调频</h1></div>
      </div>

      <section className="tune-intro">
        <h2>告诉我你想听什么</h2>
        <p>让 WaveCast 为你策划一档专属电台。</p>
      </section>

      <section className="tune-composer">
        <label htmlFor="tune-prompt">比如：</label>
        <textarea
          id="tune-prompt"
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          placeholder="下雨的夜晚，想听点温柔的爵士，带一点城市感…"
          rows={4}
        />
        <button type="button" className="composer-arrow" aria-label="开始调频" onClick={() => void beginTune()}>
          <WaveIcon name="chevron" />
        </button>
      </section>

      <section className="tune-section">
        <h3>灵感试试</h3>
        <div className="chip-row">
          {INSPIRATIONS.map((item) => (
            <button type="button" className="choice-chip" key={item} onClick={() => setPrompt(item)}>{item}</button>
          ))}
        </div>
      </section>

      <section className="tune-section">
        <h3>节目时长</h3>
        <div className="duration-grid">
          {DURATIONS.map((item) => (
            <button
              type="button"
              className={duration === item.value ? "duration-option selected" : "duration-option"}
              key={item.value}
              onClick={() => setDuration(item.value)}
            >
              {item.label}
            </button>
          ))}
        </div>
      </section>

      <button type="button" className="tune-cta" onClick={() => void beginTune()} disabled={tuning || prompt.trim().length < 2}>
        <WaveIcon name="sparkle" size={18} />
        {tuning ? "正在调频…" : "开始调频"}
      </button>

      {error ? <p className="inline-error tune-error">{error}</p> : null}

      {tuning ? (
        <section className="tuning-state" aria-live="polite">
          <div className="tuning-orb"><i /><i /><i /></div>
          <h2>正在为你调频…</h2>
          <p>收集灵感，挑选音乐，准备接下来的精彩内容。</p>
          <div className="tuning-lines"><span>在找合适的声音…</span><span>把节目慢慢排好…</span></div>
        </section>
      ) : null}

      {result ? (
        <section className="tune-result page-enter">
          <div className="section-title-row"><h2>先从这档开始</h2><Link href={`/program/${result.id}`}>查看节目</Link></div>
          <ProgramCard seed={result} compact />
        </section>
      ) : null}
    </AppShell>
  );
}
