// Phone UI, ported from docs/design/film/wavecast-film.html (layouts) and the
// product's Frost home (apps/web/components/home, docs/design/frost).
import type { CSSProperties, ReactNode } from "react";
import { HOME, HOST, PLAYER, ROUTE, TUNE, type Card, type Programme } from "../content";
import { SANS } from "../fonts";
import { clamp, eio, eo, p } from "../lib/math";
import { STATIONS, stationById } from "../stations";
import { Cover } from "./Cover";

export const SCREEN_W = 390;
export const SCREEN_H = 844;

const abs = (s: CSSProperties): CSSProperties => ({ position: "absolute", ...s });
const glass: CSSProperties = {
  background: "rgba(255,255,255,.64)",
  border: ".5px solid rgba(255,255,255,.9)",
  boxShadow: "0 10px 30px rgba(29,29,31,.06)",
  backdropFilter: "blur(30px)",
};

export function Layer({ op = 1, style, children }: { op?: number; style?: CSSProperties; children: ReactNode }) {
  if (op < 0.002) return null;
  return <div style={{ position: "absolute", inset: 0, opacity: op, ...style }}>{children}</div>;
}

/* ---------------- home ---------------- */

export const HOME_LAYOUT = { gridTop: 373, colX: [20, 202], cover: 168, rowH: 256 };

export function cardRect(i: number, gridTop: number, scrollY: number) {
  return { x: HOME_LAYOUT.colX[i % 2], y: gridTop + Math.floor(i / 2) * HOME_LAYOUT.rowH - scrollY, size: HOME_LAYOUT.cover };
}

function PickCard({ card, build, textOp, hideCover }: { card: Card; build: number; textOp: number; hideCover?: boolean }) {
  return (
    <div style={{ width: 168 }}>
      <div style={{ width: 168, height: 168, borderRadius: 12, overflow: "hidden", boxShadow: build > 0.6 ? "0 6px 18px rgba(29,29,31,.08)" : "none", visibility: hideCover ? "hidden" : "visible" }}>
        <Cover station={card.station} seed={card.seed} heading={card.heading} build={build} radius={0} />
      </div>
      <div style={{ opacity: textOp }}>
        <div style={{ marginTop: 8, fontSize: 15, fontWeight: 600, lineHeight: 1.4, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{card.title}</div>
        <div style={{ marginTop: 2, fontSize: 13, color: "#6E6E73" }}>{card.meta}</div>
      </div>
    </div>
  );
}

export function HomeScreen({
  cards,
  builds,
  textOps,
  scrollY,
  why,
  whyOp = 0,
  gridOp = 1,
  hideFirstCover,
  aura = "#5C7CE0",
}: {
  cards: Card[];
  builds: number[];
  textOps: number[];
  scrollY: number;
  why?: string;
  whyOp?: number;
  gridOp?: number;
  hideFirstCover?: boolean;
  aura?: string;
}) {
  const gridTop = HOME_LAYOUT.gridTop + (why ? 22 : 0);
  return (
    <div style={abs({ inset: 0, background: "#F2F2F4", color: "#1D1D1F", overflow: "hidden" })}>
      <div style={abs({ left: -100, top: -160, width: 420, height: 340, borderRadius: "50%", background: aura, opacity: 0.14, filter: "blur(80px)" })} />
      <div style={abs({ left: 0, top: -scrollY, width: SCREEN_W, height: 1400 })}>
        <div style={abs({ left: 20, right: 20, top: 58, height: 41, display: "flex", justifyContent: "space-between", alignItems: "center" })}>
          <span style={{ fontSize: 34, fontWeight: 700, letterSpacing: "-0.01em" }}>{HOME.title}</span>
          <span style={{ width: 36, height: 36, borderRadius: "50%", background: "#1D1D1F", color: "#fff", display: "grid", placeItems: "center", fontSize: 15, fontWeight: 600 }}>{HOME.avatar}</span>
        </div>
        <div style={abs({ left: 20, top: 121, fontSize: 22, fontWeight: 700 })}>电台</div>
        <div style={abs({ left: 20, top: 160, display: "flex", gap: 12 })}>
          {STATIONS.map((s) => (
            <div key={s.id} style={{ flex: "0 0 132px", height: 152, borderRadius: 20, background: s.deep, color: "#fff", padding: "14px 16px 16px", boxSizing: "border-box", display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
              <span style={{ fontSize: 30, fontWeight: 200, lineHeight: 1, letterSpacing: "-0.02em" }}>{s.freq.toFixed(1)}</span>
              <span style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                <span style={{ fontSize: 17, fontWeight: 600 }}>{s.name}</span>
                <span style={{ fontSize: 13, lineHeight: 1.4, opacity: 0.85 }}>{s.line}</span>
              </span>
            </div>
          ))}
        </div>
        <div style={abs({ left: 20, top: 334, fontSize: 22, fontWeight: 700 })}>{HOME.picks}</div>
        {why ? <div style={abs({ left: 20, top: 365, fontSize: 13, color: "#6E6E73", opacity: whyOp })}>{why}</div> : null}
        <div style={{ opacity: gridOp }}>
          {cards.map((c, i) => {
            const r = cardRect(i, gridTop, 0);
            return (
              <div key={c.heading} style={abs({ left: r.x, top: r.y })}>
                <PickCard card={c} build={builds[i]} textOp={textOps[i]} hideCover={i === 0 && hideFirstCover} />
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

/* ---------------- mini player & tab bar ---------------- */

export function MiniBar({ prog, playing, progress, op, rise }: { prog: Programme; playing: boolean; progress: number; op: number; rise: number }) {
  if (op < 0.002) return null;
  const st = stationById(prog.station);
  return (
    <div
      style={abs({
        left: 10,
        right: 10,
        bottom: 92,
        height: 60,
        borderRadius: 18,
        ...glass,
        background: "rgba(250,250,252,.86)",
        boxShadow: "0 10px 30px rgba(29,29,31,.14)",
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "0 14px 0 10px",
        boxSizing: "border-box",
        opacity: op,
        transform: `translateY(${rise.toFixed(1)}px)`,
        overflow: "hidden",
      })}
    >
      <div style={{ width: 42, height: 42, borderRadius: 8, overflow: "hidden", flexShrink: 0 }}>
        <Cover station={prog.station} seed={prog.seed} heading="" bare radius={0} />
      </div>
      <div style={{ flexGrow: 1, minWidth: 0 }}>
        <div style={{ fontSize: 15, fontWeight: 600, whiteSpace: "nowrap" }}>{prog.song}</div>
        <div style={{ fontSize: 12, color: "#6E6E73", display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ width: 5, height: 5, borderRadius: "50%", background: "#FF6B2C" }} />
          <span style={{ fontWeight: 300 }}>FM {st.freq.toFixed(1)}</span> {st.name}
        </div>
      </div>
      {playing ? (
        <svg width="22" height="22" viewBox="0 0 24 24" fill="#1D1D1F">
          <rect x="6" y="4.5" width="4" height="15" rx="1.2" />
          <rect x="14" y="4.5" width="4" height="15" rx="1.2" />
        </svg>
      ) : (
        <svg width="22" height="22" viewBox="0 0 24 24" fill="#1D1D1F">
          <path d="M7 4.8v14.4a1 1 0 0 0 1.5.86l11.5-7.2a1 1 0 0 0 0-1.72L8.5 3.94A1 1 0 0 0 7 4.8z" />
        </svg>
      )}
      <span style={abs({ left: 14, right: 14, bottom: 0, height: 2, background: "rgba(29,29,31,.08)" })} />
      <span style={abs({ left: 14, bottom: 0, height: 2, width: `${(progress * 362).toFixed(1)}px`, background: "#1D1D1F" })} />
    </div>
  );
}

export function TabBar({ active, op }: { active: 0 | 1; op: number }) {
  if (op < 0.002) return null;
  const icons = [
    <path key="h" d="M4 10.5 12 4l8 6.5V20a1 1 0 0 1-1 1h-4.5v-6h-5v6H5a1 1 0 0 1-1-1z" />,
    <g key="t">
      <rect x="2.5" y="8" width="19" height="9" rx="4.5" />
      <path d="M6.5 12.5h.01M9.5 12.5h.01M17.5 12.5h.01" />
      <path d="M13.5 5.5v13" />
    </g>,
    <g key="l">
      <rect x="4" y="4" width="4" height="16" rx="1" />
      <rect x="10" y="4" width="4" height="16" rx="1" />
      <path d="m16 5.4 3.4-0.9 2.9 13.9-3.4 0.9z" />
    </g>,
  ];
  return (
    <div
      style={abs({
        left: 0,
        right: 0,
        bottom: 0,
        height: 84,
        boxSizing: "border-box",
        padding: "8px 24px 26px",
        background: "rgba(242,242,244,.86)",
        backdropFilter: "blur(24px)",
        borderTop: ".5px solid rgba(60,60,67,.18)",
        display: "grid",
        gridTemplateColumns: "repeat(3, 1fr)",
        opacity: op,
      })}
    >
      {HOME.tabs.map((label, i) => (
        <div key={label} style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 3, fontSize: 11, fontWeight: i === active ? 600 : 500, color: i === active ? "#1D1D1F" : "#8E8E93" }}>
          <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
            {icons[i]}
          </svg>
          {label}
        </div>
      ))}
    </div>
  );
}

/* ---------------- player ---------------- */

export type PlayerState = {
  t: number;
  /** 0..1 host strip visibility, and how far the subtitles have rolled (line index, fractional). */
  host: number;
  hostRoll: number;
  play: number;
  ready: number;
  elapsed: number;
  routeBtn?: number;
};

const mmss = (s: number) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

export function PlayerScreen({ prog, st, hideCover, children }: { prog: Programme; st: PlayerState; hideCover?: boolean; children?: ReactNode }) {
  const station = stationById(prog.station);
  const vu = [0, 1, 2, 3, 4].map((i) => (st.host > 0.5 ? 3 + 9 * Math.abs(Math.sin(st.t * (6 + i * 1.7) + i)) : 3));
  return (
    <div style={abs({ inset: 0, background: "#221C2C", color: "#fff", overflow: "hidden" })}>
      <div style={abs({ left: -160, top: -120, width: 710, height: 710, filter: "blur(70px) saturate(1.3)", opacity: 0.9 })}>
        <Cover station={prog.station} seed={prog.seed} heading="" bare radius={0} />
      </div>
      <div style={abs({ inset: 0, background: "rgba(18,14,26,.45)" })} />
      <div style={abs({ left: 177, top: 58, width: 36, height: 5, borderRadius: 3, background: "rgba(255,255,255,.5)" })} />
      <div style={abs({ left: 24, top: 72, right: 24, height: 44, display: "flex", alignItems: "center", justifyContent: "space-between" })}>
        <span style={{ width: 40, height: 40, borderRadius: "50%", background: "rgba(255,255,255,.14)", display: "grid", placeItems: "center" }}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <path d="m6 9 6 6 6-6" />
          </svg>
        </span>
        <span style={{ display: "flex", alignItems: "center", gap: 8, height: 32, padding: "0 14px", borderRadius: 999, background: "rgba(255,255,255,.14)", fontSize: 13, fontWeight: 500 }}>
          <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#FF6B2C" }} />
          <span style={{ fontWeight: 300 }}>FM {station.freq.toFixed(1)}</span>
          <span>{station.name}</span>
        </span>
        <span style={{ width: 40, height: 40, borderRadius: "50%", background: "rgba(255,255,255,.14)", display: "grid", placeItems: "center" }}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="#fff">
            <circle cx="5" cy="12" r="1.7" />
            <circle cx="12" cy="12" r="1.7" />
            <circle cx="19" cy="12" r="1.7" />
          </svg>
        </span>
      </div>
      <div style={abs({ left: 47, top: 136, width: 296, height: 296, borderRadius: 12, overflow: "hidden", boxShadow: "0 22px 50px rgba(0,0,0,.4)", visibility: hideCover ? "hidden" : "visible" })}>
        <Cover station={prog.station} seed={prog.seed} heading={prog.heading} radius={0} />
      </div>
      <div style={abs({ left: 24, top: 452, right: 24 })}>
        <div style={{ fontSize: 22, fontWeight: 600 }}>{prog.song}</div>
        <div style={{ fontSize: 19, color: "rgba(255,255,255,.62)" }}>{prog.artist}</div>
      </div>
      <div style={abs({ left: 24, right: 24, top: 520, height: 92, borderRadius: 18, background: "rgba(255,255,255,.13)", overflow: "hidden" })}>
        <div style={abs({ left: 14, right: 14, top: 12, opacity: 1 - st.host })}>
          <div style={{ fontSize: 13, fontWeight: 600, color: "rgba(255,255,255,.8)", display: "flex", gap: 8, alignItems: "center" }}>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="#fff">
              <path d="M5 4.5v15l12-7.5z" />
            </svg>
            {PLAYER.upNext}
          </div>
          <div style={{ marginTop: 6, fontSize: 15 }}>{prog.next}</div>
          <div style={{ fontSize: 13, color: "rgba(255,255,255,.55)" }}>{prog.nextChapter}</div>
        </div>
        <div style={abs({ left: 14, right: 14, top: 12, opacity: st.host })}>
          <div style={{ fontSize: 13, fontWeight: 600, color: "rgba(255,255,255,.8)", display: "flex", gap: 8, alignItems: "center" }}>
            <span style={{ display: "flex", gap: 2, alignItems: "center", height: 12 }}>
              {vu.map((h, i) => (
                <span key={i} style={{ width: 2.5, height: h, borderRadius: 1, background: "#fff" }} />
              ))}
            </span>
            {PLAYER.hostSpeaking}
            <span style={{ marginLeft: "auto", fontWeight: 400, color: "rgba(255,255,255,.6)", fontSize: 12 }}>{PLAYER.fullText}</span>
          </div>
          <div style={{ position: "relative", marginTop: 6, height: 45, overflow: "hidden", WebkitMaskImage: "linear-gradient(180deg,transparent 0,#000 9px)", maskImage: "linear-gradient(180deg,transparent 0,#000 9px)" }}>
            <div style={abs({ left: 0, right: 0, top: 0, fontSize: 15, lineHeight: "22.5px", transform: `translateY(${(-st.hostRoll * 22.5).toFixed(2)}px)` })}>
              {HOST.map((s) => (
                <div key={s}>{s}</div>
              ))}
            </div>
          </div>
        </div>
      </div>
      <div style={abs({ left: 24, right: 24, top: 630 })}>
        <div style={{ position: "relative", height: 6, borderRadius: 3, background: "repeating-linear-gradient(90deg,rgba(255,255,255,.22) 0 3px,transparent 3px 7px)", overflow: "hidden" }}>
          <span style={abs({ left: 0, top: 0, bottom: 0, width: `${(st.ready * 100).toFixed(2)}%`, background: "rgba(255,255,255,.34)" })} />
          <span style={abs({ left: 0, top: 0, bottom: 0, width: `${(st.play * 100).toFixed(2)}%`, background: "#fff" })} />
        </div>
        <div style={{ marginTop: 8, display: "flex", justifyContent: "space-between", fontSize: 12, color: "rgba(255,255,255,.6)", fontVariantNumeric: "tabular-nums" }}>
          <span>{mmss(st.elapsed)}</span>
          <span>{prog.total}</span>
        </div>
      </div>
      <div style={abs({ left: 46, right: 46, top: 672, height: 72, display: "flex", alignItems: "center", justifyContent: "space-between" })}>
        <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
          <path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3" />
          <path d="M4.5 3.8v3.7h3.7" />
          <text x="12.4" y="15.4" textAnchor="middle" fontSize="7" fontWeight="600" fill="#fff" stroke="none" style={{ fontFamily: SANS }}>
            15
          </text>
        </svg>
        <svg width="46" height="46" viewBox="0 0 24 24" fill="#fff">
          <rect x="5.5" y="4" width="4.5" height="16" rx="1.4" />
          <rect x="14" y="4" width="4.5" height="16" rx="1.4" />
        </svg>
        <svg width="34" height="34" viewBox="0 0 24 24" fill="#fff">
          <path d="M4 5.8v12.4a.8.8 0 0 0 1.2.7l9.4-6.2a.8.8 0 0 0 0-1.4L5.2 5.1a.8.8 0 0 0-1.2.7z" />
          <rect x="16.8" y="5" width="2.6" height="14" rx="1" />
        </svg>
      </div>
      <div style={abs({ left: 36, right: 36, top: 764, height: 44, display: "flex", alignItems: "center", justifyContent: "space-between" })}>
        <span style={{ width: 44, height: 44, borderRadius: 12, background: "rgba(255,255,255,.2)", display: "grid", placeItems: "center" }}>
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="1.8" strokeLinecap="round">
            <rect x="3" y="5" width="18" height="14" rx="3" />
            <path d="M7 11h10M7 15h6" />
          </svg>
        </span>
        <span style={{ width: 44, height: 44, borderRadius: 12, display: "grid", placeItems: "center", background: `rgba(255,255,255,${(0.2 * (st.routeBtn ?? 0)).toFixed(3)})` }}>
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="rgba(255,255,255,.8)" strokeWidth="1.8" strokeLinecap="round">
            <path d="M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01" />
          </svg>
        </span>
      </div>
      {children}
    </div>
  );
}

export function RouteSheet({ t, at, out }: { t: number; at: number; out: number }) {
  const rIn = eo(p(t, at, at + 0.6));
  const rOut = eio(p(t, out, out + 0.6));
  const y = (1 - rIn) * 620 + rOut * 620;
  if (y >= 619) return null;
  return (
    <div
      style={abs({
        left: 0,
        right: 0,
        bottom: 0,
        height: 600,
        borderRadius: "28px 28px 0 0",
        background: "rgba(36,30,48,.95)",
        backdropFilter: "blur(40px) saturate(1.4)",
        borderTop: ".5px solid rgba(255,255,255,.18)",
        padding: "10px 20px 34px",
        boxSizing: "border-box",
        transform: `translateY(${y.toFixed(1)}px)`,
      })}
    >
      <div style={{ width: 36, height: 5, borderRadius: 3, background: "rgba(255,255,255,.35)", margin: "0 auto" }} />
      <div style={{ marginTop: 14, fontSize: 22, fontWeight: 700 }}>{ROUTE.title}</div>
      <div style={{ fontSize: 13, color: "rgba(255,255,255,.6)" }}>{ROUTE.sub}</div>
      <div style={{ marginTop: 18, display: "flex", flexDirection: "column", gap: 6 }}>
        {ROUTE.chapters.map((c, i) => {
          // Chapters surface one after another once the sheet is up.
          const show = eo(p(t, at + 0.7 + i * 0.55, at + 1.3 + i * 0.55));
          const base = [1, 1, 0.7, 0.55][i];
          return (
            <div
              key={c.at}
              style={{
                borderRadius: 16,
                padding: "12px 14px",
                background: i === 0 ? "rgba(255,255,255,.12)" : i === 1 ? "rgba(255,255,255,.05)" : "transparent",
                opacity: base * show,
                transform: `translateY(${((1 - show) * 20).toFixed(1)}px)`,
                filter: `blur(${((1 - show) * 6).toFixed(1)}px)`,
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span>
                  <span style={{ fontSize: 13, fontWeight: 300, color: "rgba(255,255,255,.6)", marginRight: 8, fontVariantNumeric: "tabular-nums" }}>{c.at}</span>
                  <span style={{ fontSize: 16, fontWeight: 600 }}>{c.title}</span>
                </span>
                <span style={{ fontSize: 12, fontWeight: 500, color: i === 0 ? "#FF8A55" : "rgba(255,255,255,.55)" }}>{c.state}</span>
              </div>
              {c.tracks.map(([n, s]) => (
                <div key={n} style={{ marginTop: 8, fontSize: 14, color: s === 1 ? "#fff" : s === 2 ? "rgba(255,255,255,.5)" : "rgba(255,255,255,.78)", display: "flex", gap: 10, alignItems: "center" }}>
                  <span style={{ width: 14, display: "flex", gap: 1.5, alignItems: "flex-end", height: 12 }}>
                    {s === 1
                      ? [6, 12, 8].map((h, k) => <span key={k} style={{ width: 3, height: 4 + (h - 4) * Math.abs(Math.sin(t * (5 + k * 2) + k)), background: "#FF6B2C" }} />)
                      : null}
                  </span>
                  {n}
                </div>
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ---------------- tuner ---------------- */

const LO = 84;
const HI = 112;
const PX = 38.75;
const STRIP_W = (HI - LO) * PX;

function TunerStrip({ freq }: { freq: number }) {
  let minor = "";
  let major = "";
  const labels: ReactNode[] = [];
  for (let i = LO * 5; i <= HI * 5; i++) {
    const f = i / 5;
    const x = ((f - LO) * PX).toFixed(1);
    const isInt = i % 5 === 0;
    const len = isInt ? 18 : 7;
    const d = `M${x} ${52 - len}V52`;
    if (isInt) major += d;
    else minor += d;
    if (isInt && i % 10 === 0)
      labels.push(
        <text key={i} x={x} y={72} textAnchor="middle" fontSize={12} fontWeight={300} fill="#8E8E93" style={{ fontFamily: SANS }}>
          {f}
        </text>,
      );
  }
  for (let f = LO + 0.5; f < HI; f += 1) minor += `M${((f - LO) * PX).toFixed(1)} 40V52`;
  return (
    <svg width={STRIP_W} height={96} viewBox={`0 0 ${STRIP_W} 96`} style={abs({ left: 0, top: 0, transform: `translateX(${(155 - (freq - LO) * PX).toFixed(2)}px)` })}>
      <path d={minor} stroke="rgba(29,29,31,.22)" strokeWidth={1} strokeLinecap="round" />
      <path d={major} stroke="rgba(29,29,31,.5)" strokeWidth={1.2} strokeLinecap="round" />
      {labels}
      {STATIONS.map((s) => {
        const x = (s.freq - LO) * PX;
        return (
          <g key={s.id}>
            <circle cx={x - 26} cy={16} r={2.5} fill={s.light} />
            <text x={x - 20} y={20} fontSize={12} fontWeight={500} fill="#6E6E73" style={{ fontFamily: SANS }}>
              {s.name}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

const NOISE = (() => {
  let s = 7;
  const R = () => (s = (s * 16807) % 2147483647) / 2147483647;
  let d = "";
  for (let k = 0; k < 240; k++) {
    const x = R() * 310;
    const y = R() * 96;
    const rr = 0.4 + R() * 0.6;
    d += `M${(x - rr).toFixed(2)} ${y.toFixed(2)}a${rr.toFixed(2)} ${rr.toFixed(2)} 0 1 0 ${(2 * rr).toFixed(2)} 0a${rr.toFixed(2)} ${rr.toFixed(2)} 0 1 0 ${(-2 * rr).toFixed(2)} 0Z`;
  }
  return d;
})();

const WINDOW: CSSProperties = {
  width: 310,
  height: 96,
  borderRadius: 18,
  background: "rgba(226,226,232,.8)",
  boxShadow: "inset 0 2px 6px rgba(29,29,31,.16),inset 0 1px 1px rgba(29,29,31,.08),0 1px 0 #fff",
  overflow: "hidden",
};
const FADE_L = abs({ left: 0, top: 0, bottom: 0, width: 48, background: "linear-gradient(90deg,rgba(228,228,234,.96),rgba(228,228,234,0))" });
const FADE_R = abs({ right: 0, top: 0, bottom: 0, width: 48, background: "linear-gradient(270deg,rgba(228,228,234,.96),rgba(228,228,234,0))" });

export function TuneScreen({ t, freq, typed, chip, ctaPress, caret }: { t: number; freq: number; typed: string; chip: number; ctaPress: number; caret: boolean }) {
  let near = STATIONS[0];
  let dist = 99;
  for (const s of STATIONS) {
    const d = Math.abs(s.freq - freq);
    if (d < dist) {
      dist = d;
      near = s;
    }
  }
  const locked = dist < 0.18;
  return (
    <div style={abs({ inset: 0, background: "#F2F2F4", color: "#1D1D1F", overflow: "hidden" })}>
      <div style={abs({ left: -90, top: -140, width: 460, height: 420, borderRadius: "50%", background: locked ? near.light : "#B8B8C0", opacity: 0.32, filter: "blur(80px)" })} />
      <div style={abs({ left: 20, top: 58, fontSize: 34, fontWeight: 700 })}>{TUNE.title}</div>
      <div style={abs({ left: 20, top: 115, width: 350, height: 300, borderRadius: 28, padding: 20, boxSizing: "border-box", ...glass })}>
        <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between" }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
            <span style={{ fontSize: 15, fontWeight: 500, color: "#6E6E73" }}>FM</span>
            <span style={{ fontSize: 56, fontWeight: 200, lineHeight: 1, letterSpacing: "-0.03em", fontVariantNumeric: "tabular-nums" }}>{freq.toFixed(1)}</span>
          </div>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 3, height: 18, paddingBottom: 8 }}>
            {[6, 9, 12, 15, 18].map((h, i) => (
              <span key={h} style={{ width: 4, borderRadius: 1.5, height: h, background: i < (locked ? 5 : 1) ? "#1D1D1F" : "rgba(29,29,31,.15)" }} />
            ))}
          </div>
        </div>
        <div style={{ marginTop: 12, display: "flex", alignItems: "center", gap: 8, height: 28 }}>
          <span style={{ fontSize: 20, fontWeight: 600, color: locked ? "#1D1D1F" : "#8E8E93" }}>{locked ? near.name : TUNE.between}</span>
          <span style={{ fontSize: 12, fontWeight: 500, padding: "3px 8px", borderRadius: 999, background: "rgba(62,156,140,.16)", color: "#2E7D70", opacity: chip }}>{TUNE.matched}</span>
        </div>
        <div style={{ marginTop: 4, fontSize: 15, color: "#6E6E73", height: 22 }}>{locked ? near.description.replace(/。.*$/, "") : TUNE.betweenHint}</div>
        <div style={abs({ left: 20, top: 150, ...WINDOW })}>
          <TunerStrip freq={freq} />
          <svg width={310} height={96} style={abs({ left: 0, top: 0, opacity: locked ? 0 : Math.min(1, (dist - 0.18) * 2) })}>
            <path d={NOISE} fill="rgba(29,29,31,.18)" />
          </svg>
          <div style={FADE_L} />
          <div style={FADE_R} />
          <div style={abs({ left: 154, top: 8, bottom: 8, width: 2, borderRadius: 1, background: "#FF6B2C", boxShadow: "0 0 8px rgba(255,107,44,.55)" })} />
        </div>
        <div style={abs({ left: 20, top: 258, width: 310, height: 26, borderRadius: 13, background: "linear-gradient(180deg,rgba(29,29,31,.07),rgba(255,255,255,.75) 50%,rgba(29,29,31,.09))", overflow: "hidden" })}>
          <svg width={330} height={26} style={{ transform: `translateX(${(-(((freq - 84) * 38.75) % 10)).toFixed(2)}px)` }}>
            <path d={Array.from({ length: 34 }, (_, k) => `M${k * 10} 7V19`).join("")} stroke="rgba(29,29,31,.16)" strokeWidth={1} />
          </svg>
        </div>
      </div>
      <div style={abs({ left: 20, top: 431, width: 350, height: 56, borderRadius: 16, background: "rgba(255,255,255,.75)", border: ".5px solid rgba(255,255,255,.9)", padding: "0 18px", boxSizing: "border-box", display: "flex", alignItems: "center", fontSize: 17 })}>
        <span style={{ whiteSpace: "nowrap", overflow: "hidden" }}>{typed}</span>
        <span style={{ width: 2, height: 22, background: "#FF6B2C", marginLeft: 2, opacity: caret ? 1 : 0 }} />
        {typed ? null : <span style={abs({ left: 18, color: "#8E8E93" })}>{TUNE.placeholder}</span>}
      </div>
      <div style={abs({ left: 20, top: 503, width: 350, height: 42, borderRadius: 12, background: "rgba(118,118,128,.12)", display: "grid", gridTemplateColumns: "repeat(3,1fr)", padding: 3, boxSizing: "border-box", fontSize: 14, textAlign: "center", alignItems: "center" })}>
        {TUNE.durations.map((d, i) => (
          <span key={d} style={i === 1 ? { background: "#fff", borderRadius: 9, height: 36, lineHeight: "36px", fontWeight: 600, boxShadow: "0 2px 6px rgba(0,0,0,.1)" } : undefined}>
            {d}
          </span>
        ))}
      </div>
      <div
        style={abs({
          left: 20,
          top: 561,
          width: 350,
          height: 54,
          borderRadius: 999,
          background: "#1D1D1F",
          color: "#fff",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          gap: 10,
          fontSize: 17,
          fontWeight: 600,
          transform: `scale(${(1 - 0.04 * ctaPress).toFixed(4)})`,
        })}
      >
        <span style={{ width: 8, height: 8, borderRadius: "50%", background: "#FF6B2C", boxShadow: "0 0 0 4px rgba(255,107,44,.25)" }} />
        <span>{locked ? TUNE.ctaLocked(near.freq.toFixed(1)) : TUNE.ctaBetween}</span>
      </div>
      <span style={{ display: "none" }}>{t}</span>
    </div>
  );
}

/** "开播中": the tuner window locked on the chosen station, the signal cleaning up. */
export function TuningScreen({ t, at, stationId }: { t: number; at: number; stationId: Parameters<typeof stationById>[0] }) {
  const st = stationById(stationId);
  const clean = eo(p(t, at + 0.4, at + 4));
  let wd = "";
  for (let x = 0; x <= 300; x += 3) {
    const nz = Math.sin(x * 0.21 + t * 7.3) * 0.5 + Math.sin(x * 0.53 - t * 5.1) * 0.3 + Math.sin(x * 1.13 + t * 11.7) * 0.2;
    const sn = Math.sin(x * 0.12 - t * 5.0);
    const y = 28 + nz * 20 * (1 - clean) + sn * 12 * (0.3 + 0.7 * clean);
    wd += `${x ? "L" : "M"}${x} ${y.toFixed(1)}`;
  }
  const wob = Math.exp(-p(t, at, at + 1.2) * 4) * Math.sin((t - at) * 20) * 10 * (t < at + 1.2 ? 1 : 0);
  return (
    <div style={abs({ inset: 0, background: "#F2F2F4", color: "#1D1D1F", overflow: "hidden" })}>
      <div style={abs({ left: -60, top: 80, width: 520, height: 520, borderRadius: "50%", background: st.light, opacity: 0.34, filter: "blur(90px)" })} />
      <div style={abs({ left: 20, top: 58, height: 36, padding: "0 14px", borderRadius: 999, background: "rgba(118,118,128,.14)", fontSize: 15, fontWeight: 500, lineHeight: "36px" })}>{TUNE.cancel}</div>
      <div style={abs({ left: 20, top: 140, width: 350, height: 330, borderRadius: 28, display: "flex", flexDirection: "column", alignItems: "center", paddingTop: 22, boxSizing: "border-box", ...glass })}>
        <div style={{ position: "relative", ...WINDOW }}>
          <TunerStrip freq={st.freq} />
          <div style={FADE_L} />
          <div style={FADE_R} />
          <div style={abs({ left: 154, top: 8, bottom: 8, width: 2, borderRadius: 1, background: "#FF6B2C", boxShadow: "0 0 10px rgba(255,107,44,.6)", transform: `translateX(${wob.toFixed(1)}px)` })} />
        </div>
        <div style={{ marginTop: 14, display: "flex", alignItems: "baseline", gap: 6 }}>
          <span style={{ fontSize: 15, fontWeight: 500, color: "#6E6E73" }}>FM</span>
          <span style={{ fontSize: 56, fontWeight: 200, lineHeight: 1, letterSpacing: "-0.03em" }}>{st.freq.toFixed(1)}</span>
        </div>
        <div style={{ marginTop: 8, fontSize: 20, fontWeight: 600 }}>{st.name}</div>
        <svg width={300} height={56} style={{ marginTop: 14 }}>
          <path d={wd} fill="none" stroke={st.deep} strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </div>
      <div style={abs({ left: 0, right: 0, bottom: 40, textAlign: "center", fontSize: 14, lineHeight: 1.6, color: "#6E6E73" })}>
        {TUNE.tuningHint.map((l) => (
          <div key={l}>{l}</div>
        ))}
      </div>
    </div>
  );
}

/* ---------------- finger ---------------- */

export type Gesture = { a: number; b: number; x0: number; y0: number; x1: number; y1: number; tap?: boolean; path?: (x: number) => [number, number] };

export function Finger({ t, gestures }: { t: number; gestures: Gesture[] }) {
  for (const g of gestures) {
    if (t >= g.a && t <= g.b) {
      const x = p(t, g.a, g.b);
      const e = eio(x);
      const [fx, fy] = g.path ? g.path(x) : [g.x0 + (g.x1 - g.x0) * e, g.y0 + (g.y1 - g.y0) * e];
      const fade = Math.min(1, p(t, g.a, g.a + 0.15), 1 - p(t, g.b - 0.15, g.b));
      const s = g.tap ? 1 - 0.18 * Math.sin(Math.PI * x) : 1;
      return (
        <div
          style={abs({
            left: fx - 23,
            top: fy - 23,
            width: 46,
            height: 46,
            borderRadius: "50%",
            background: "rgba(255,255,255,.55)",
            border: "1.5px solid rgba(255,255,255,.9)",
            boxShadow: "0 4px 14px rgba(0,0,0,.18)",
            opacity: clamp(fade) * 0.95,
            transform: `scale(${s.toFixed(3)})`,
          })}
        />
      );
    }
  }
  return null;
}
