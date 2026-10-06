import type { CSSProperties, ReactNode } from "react";
import { CHAPTERS, LINES } from "../content";
import { SANS } from "../fonts";
import { ei, eio, eo, lerp, p } from "../lib/math";
import { darkness } from "../scene";
import { AFTERNOON, CALL_HOLD, CHAPTER_AT, CHAPTER_OUT, MORNING, NEXT, NIGHT } from "../timeline";

export const MARGIN_X = 128;

/** The brief's text entrance: opacity, 20px rise, 10px blur → 0 over 0.8 s, fast then slow. */
export function textIn(t: number, at: number, out: number | null, dur = 0.8, outDur = 0.6): CSSProperties & { op: number } {
  const i = eo(p(t, at, at + dur));
  const o = out == null ? 0 : ei(p(t, out, out + outDur));
  const op = i * (1 - o);
  return {
    op,
    opacity: op,
    transform: `translateY(${((1 - i) * 20 - o * 10).toFixed(2)}px)`,
    filter: `blur(${((1 - i) * 10 + o * 6).toFixed(2)}px)`,
    visibility: op < 0.002 ? "hidden" : "visible",
  };
}

function ink(t: number, alpha = 1) {
  const d = darkness(t);
  const v = Math.round(lerp(0x1d, 0xf5, d));
  return `rgba(${v},${v},${Math.round(lerp(0x1f, 0xf7, d))},${alpha})`;
}

function Text({ style, children }: { style: CSSProperties & { op?: number }; children: ReactNode }) {
  const { op, ...rest } = style;
  if (op !== undefined && op < 0.002) return null;
  return <div style={{ position: "absolute", fontFamily: SANS, ...rest }}>{children}</div>;
}

type ChapterKey = keyof typeof CHAPTERS;

function ChapterCard({ t, k }: { t: number; k: ChapterKey }) {
  const at = CHAPTER_AT[k];
  const out = CHAPTER_OUT[k];
  if (t < at - 0.1 || t > out + 1) return null;
  const c = CHAPTERS[k];
  const shrink = eio(p(t, at + CALL_HOLD + 0.2, at + CALL_HOLD + 1.0));
  const s = lerp(1, 0.52, shrink);
  const x = lerp(MARGIN_X, 72, shrink);
  const y = lerp(96, 58, shrink);
  const enter = textIn(t, at, out);
  const sub = textIn(t, at + 0.25, out);
  const color = ink(t);
  return (
    <div style={{ position: "absolute", left: x, top: y, transform: `scale(${s.toFixed(4)})`, transformOrigin: "0 0", fontFamily: SANS, color }}>
      <div style={{ fontSize: 132, fontWeight: 200, lineHeight: 1, letterSpacing: "-0.02em", fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap", ...strip(enter) }}>{c.time}</div>
      {c.freq ? (
        <div style={{ marginTop: 22, display: "flex", alignItems: "center", gap: 14, fontSize: 30, whiteSpace: "nowrap", ...strip(sub) }}>
          <span style={{ width: 10, height: 10, borderRadius: "50%", background: "#FF6B2C", boxShadow: "0 0 10px rgba(255,107,44,.6)" }} />
          <span style={{ fontWeight: 300, fontVariantNumeric: "tabular-nums" }}>{c.freq}</span>
          <span style={{ fontWeight: 500 }}>{c.station}</span>
        </div>
      ) : null}
    </div>
  );
}

const strip = ({ op: _op, ...rest }: CSSProperties & { op: number }) => rest;

function StationCall({ t, k }: { t: number; k: ChapterKey }) {
  const at = CHAPTER_AT[k];
  if (t < at || t > at + CALL_HOLD + 1) return null;
  const st = textIn(t, at + 0.2, at + CALL_HOLD - 0.6, 0.8, 0.6);
  return <Subtitle t={t} style={st} text={CHAPTERS[k].call} />;
}

/** Bottom-centred line: station calls and the night host lines. */
export function Subtitle({ t, style, text }: { t: number; style: CSSProperties & { op: number }; text: string }) {
  const d = darkness(t);
  const shadow = d > 0.5 ? "0 2px 18px rgba(0,0,0,.55), 0 0 2px rgba(0,0,0,.4)" : "0 2px 18px rgba(255,248,240,.9), 0 0 2px rgba(255,255,255,.6)";
  return (
    <Text style={{ left: 0, right: 0, bottom: 46, textAlign: "center", fontSize: 38, fontWeight: 400, letterSpacing: "0.02em", color: ink(t), textShadow: shadow, ...style }}>
      {text}
    </Text>
  );
}

/** Left-hand product lines: 46px / 600, two short lines. */
function SideLine({ t, lines, at, out, top = 452 }: { t: number; lines: string[]; at: number; out: number; top?: number }) {
  if (t < at - 0.1 || t > out + 1) return null;
  return (
    <Text style={{ left: MARGIN_X, top, width: 760, fontSize: 46, fontWeight: 600, lineHeight: 1.32, letterSpacing: "-0.01em", color: ink(t), ...textIn(t, at, out) }}>
      {lines.map((l) => (
        <div key={l}>{l}</div>
      ))}
    </Text>
  );
}

export function TextLayer({ t }: { t: number }) {
  return (
    <>
      {(Object.keys(CHAPTERS) as ChapterKey[]).map((k) => (
        <ChapterCard key={k} t={t} k={k} />
      ))}
      {(Object.keys(CHAPTERS) as ChapterKey[]).map((k) => (
        <StationCall key={k} t={t} k={k} />
      ))}
      <SideLine t={t} lines={LINES.morning[0]} at={MORNING.line1[0]} out={MORNING.line1[1]} />
      <SideLine t={t} lines={LINES.morning[1]} at={MORNING.line2[0]} out={MORNING.line2[1]} />
      <SideLine t={t} lines={LINES.afternoon[0]} at={AFTERNOON.line1[0]} out={AFTERNOON.line1[1]} />
      <SideLine t={t} lines={LINES.afternoon[1]} at={AFTERNOON.line2[0]} out={AFTERNOON.line2[1]} />
      <SideLine t={t} lines={LINES.night[0]} at={NIGHT.line1[0]} out={NIGHT.line1[1]} top={300} />
      <SideLine t={t} lines={LINES.night[1]} at={NIGHT.line2[0]} out={NIGHT.line2[1]} />
      <SideLine t={t} lines={LINES.night[2]} at={NIGHT.line3[0]} out={NIGHT.line3[1]} />
      <SideLine t={t} lines={LINES.nextMorning[0]} at={NEXT.line1[0]} out={NEXT.line1[1]} />
    </>
  );
}

