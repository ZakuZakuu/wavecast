// The demo film: a frame-exact port of render(t) from the approved sample
// (docs/design/film/wavecast-film.html), with t = frame / fps. Everything on
// screen is a pure function of t; there is no Math.random anywhere.
import type { CSSProperties, ReactNode } from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { logoMarkSvg } from "../../web/lib/brand/logo-mark";
import { content, type Card } from "./content";
import { clamp, ei, eio, eo, lerp, p, sp } from "./lib/anim";
import { circ, makeCover, type Cover } from "./lib/cover";
import { SANS } from "./lib/fonts";
import { STA, station } from "./lib/stations";
import { ANCHOR, CAPTIONS, cam, FINGER, HOST_IN, HOST_OUT, RIG, tuneF, typed } from "./timeline";
import { Sfx } from "./Sfx";

const INK = "#1D1D1F";
const SUB = "#6E6E73";
const ACCENT = "#FF6B2C";
const NIGHT = station("night").c;

/* ---------------- motion helpers (reveal / show in the sample) ---------------- */

function reveal(t: number, a: number, b: number | null, rise = 26): CSSProperties {
  const i = eo(p(t, a, a + 0.7)),
    o = b == null ? 0 : ei(p(t, b, b + 0.5));
  const op = i * (1 - o);
  return {
    opacity: op,
    visibility: op < 0.002 ? "hidden" : "visible",
    transform: `translateY(${((1 - i) * rise - o * 14).toFixed(2)}px)`,
    filter: `blur(${((1 - i) * 10 + o * 8).toFixed(2)}px)`,
  };
}

function show(t: number, a: number, b: number | null, dy = 18): CSSProperties {
  const i = sp(t, a, a + 0.6),
    o = b == null ? 0 : sp(t, b, b + 0.5);
  const v = i * (1 - o);
  return {
    opacity: v,
    visibility: v < 0.002 ? "hidden" : "visible",
    transform: `translateY(${((1 - i) * dy - o * 10).toFixed(1)}px) scale(${(0.985 + 0.015 * i).toFixed(4)})`,
  };
}

function fingerStyle(t: number, fps: number): CSSProperties {
  for (const k of FINGER) {
    if (t >= k.a && t <= k.b) {
      const x = p(t, k.a, k.b),
        e = eio(x);
      const dt = 1 / fps,
        e2 = eio(p(t + dt, k.a, k.b));
      const speed = Math.hypot(k.x1 - k.x0, k.y1 - k.y0) * (e2 - e) * fps;
      const fade = Math.min(1, p(t, k.a, k.a + 0.15), 1 - p(t, k.b - 0.15, k.b));
      return {
        left: lerp(k.x0, k.x1, e),
        top: lerp(k.y0, k.y1, e),
        opacity: fade * 0.95,
        transform: `scale(${k.tap ? 1 - 0.18 * Math.sin(Math.PI * x) : 1})`,
        filter: speed > 1 ? `blur(${Math.min(1.5, (speed / fps) * 0.12).toFixed(2)}px)` : undefined,
      };
    }
  }
  return { opacity: 0 };
}

const abs = (s: CSSProperties): CSSProperties => ({ position: "absolute", ...s });
const glass: CSSProperties = {
  background: "rgba(255,255,255,.64)",
  border: ".5px solid rgba(255,255,255,.9)",
  boxShadow: "0 10px 30px rgba(29,29,31,.06)",
  backdropFilter: "blur(30px)",
};
const lines = (s: string) => s.split("\n").map((l, i) => (i ? [<br key={i} />, l] : l));

/* ---------------- covers ---------------- */

const coverCache = new Map<string, Cover>();
function cover(card: { station: Card["station"]; seed: number }, heading: string) {
  const key = `${card.station}|${card.seed}|${heading}`;
  let c = coverCache.get(key);
  if (!c) coverCache.set(key, (c = makeCover(card.station, card.seed, heading)));
  return c;
}

/** A cover; `build` (0..1) reveals it layer by layer like the sample's buildProgress. */
function CoverView({ cv, bare, build, style }: { cv: Cover; bare?: boolean; build?: number; style?: CSSProperties }) {
  const layers = bare ? cv.parts : [...cv.parts, cv.text];
  const n = layers.length;
  return (
    <div style={{ overflow: "hidden", ...style }}>
      <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice" style={{ display: "block", width: "100%", height: "100%", fontFamily: SANS }}>
        <rect width="100" height="100" fill={cv.bg} />
        {layers.map((g, i) => {
          const l = build == null ? 1 : clamp(build * (n + 0.6) - i);
          return (
            <g
              key={i}
              style={{ opacity: l, transform: `scale(${0.9 + 0.1 * eo(l)})`, transformBox: "fill-box", transformOrigin: "center" }}
              dangerouslySetInnerHTML={{ __html: g }}
            />
          );
        })}
      </svg>
    </div>
  );
}

function HomeCard({ card, build, textOpacity = 1 }: { card: Card; build: number; textOpacity?: number }) {
  return (
    <div>
      <CoverView cv={cover(card, card.heading)} build={build} style={{ width: 165, height: 165, borderRadius: 12, boxShadow: "0 6px 18px rgba(29,29,31,.08)" }} />
      <div
        style={{
          opacity: textOpacity,
          marginTop: 8,
          fontSize: 14,
          fontWeight: 600,
          lineHeight: 1.35,
          display: "-webkit-box",
          WebkitLineClamp: 2,
          WebkitBoxOrient: "vertical",
          overflow: "hidden",
        }}
      >
        {card.title}
      </div>
      <div style={{ opacity: textOpacity, fontSize: 12, color: SUB, marginTop: 2 }}>{card.meta}</div>
    </div>
  );
}

/* ---------------- static artwork (built once) ---------------- */

const STRIP_LO = 84,
  STRIP_HI = 112,
  STRIP_PX = 38.75,
  STRIP_W = (STRIP_HI - STRIP_LO) * STRIP_PX;
const STRIP_SVG = (() => {
  let mi = "",
    ma = "",
    tx = "",
    lb = "";
  for (let i = STRIP_LO * 5; i <= STRIP_HI * 5; i++) {
    const f = i / 5,
      x = ((f - STRIP_LO) * STRIP_PX).toFixed(1),
      isInt = i % 5 === 0,
      isHalf = !isInt && Math.abs(f * 2 - Math.round(f * 2)) < 1e-6;
    const len = isInt ? 18 : isHalf ? 12 : 7;
    const s = "M" + x + " " + (52 - len) + "V52";
    if (isInt) ma += s;
    else mi += s;
    if (isInt && i % 10 === 0) tx += `<text x="${x}" y="72" text-anchor="middle" font-size="12" font-weight="300" fill="#8E8E93">${f}</text>`;
  }
  STA.forEach((s) => {
    const x = (s.f - STRIP_LO) * STRIP_PX;
    lb += `<circle cx="${x - 26}" cy="16" r="2.5" fill="${s.c}"/><text x="${x - 20}" y="20" font-size="12" font-weight="500" fill="#6E6E73">${s.n}</text>`;
  });
  return `<path d="${mi}" stroke="rgba(29,29,31,.22)" stroke-width="1" stroke-linecap="round"/><path d="${ma}" stroke="rgba(29,29,31,.5)" stroke-width="1.2" stroke-linecap="round"/>${tx}${lb}`;
})();
const KNURL = (() => {
  let d = "";
  for (let k = 0; k <= 33; k++) d += "M" + k * 10 + " 7V19";
  return d;
})();
const NOISE = (() => {
  // Fixed-seed Lehmer generator, exactly as in the sample.
  let s = 7;
  const R = () => (s = (s * 16807) % 2147483647) / 2147483647;
  let d = "";
  for (let k = 0; k < 240; k++) {
    const x = R() * 310,
      y = R() * 96,
      rr = 0.4 + R() * 0.6;
    d += circ(x, y, rr);
  }
  return d;
})();

/** Horizontal-only blur for fast-moving SVG content (sx in px). */
const hblur = (id: string, sx: number) =>
  sx > 0.05 ? `<defs><filter id="${id}" x="-5%" y="0" width="110%" height="100%"><feGaussianBlur stdDeviation="${sx.toFixed(2)} 0"/></filter></defs>` : "";

function Strip({ x, blur = 0, id }: { x: number; blur?: number; id: string }) {
  const html = blur > 0.05 ? `${hblur(id, blur)}<g filter="url(#${id})">${STRIP_SVG}</g>` : STRIP_SVG;
  return (
    <svg
      width={STRIP_W}
      height={96}
      viewBox={`0 0 ${STRIP_W} 96`}
      style={{ position: "absolute", left: 0, top: 0, transform: `translateX(${x.toFixed(2)}px)`, fontFamily: SANS }}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

/** Light motion blur: a fraction of the per-frame travel, capped. */
const motionBlur = (pxPerSec: number, fps: number) => Math.min(3, (Math.abs(pxPerSec) / fps) * 0.35);
const stripX = (f: number) => 155 - (f - STRIP_LO) * STRIP_PX;

function Dial({ children, glow }: { children?: ReactNode; glow: number }) {
  return (
    <>
      {children}
      <div style={abs({ left: 0, top: 0, bottom: 0, width: 48, background: "linear-gradient(90deg,rgba(228,228,234,.96),rgba(228,228,234,0))" })} />
      <div style={abs({ right: 0, top: 0, bottom: 0, width: 48, background: "linear-gradient(270deg,rgba(228,228,234,.96),rgba(228,228,234,0))" })} />
      <div style={abs({ left: 154, top: 8, bottom: 8, width: 2, borderRadius: 1, background: ACCENT, boxShadow: `0 0 ${glow}px rgba(255,107,44,.55)` })} />
    </>
  );
}

const LOGO = logoMarkSvg();
const PROG = content.programme;
const NOW = cover(PROG, PROG.coverHeading);
const NOW_BARE = cover(PROG, "");

/* ---------------- the film ---------------- */

export function Film({ sfx = true }: { sfx?: boolean }) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;

  const fade = Math.max(1 - eo(p(t, 0, 1.2)), ei(p(t, 75.2, 76)));

  // rig entrance / exit + camera
  const enter = sp(t, 0.4, 2.2),
    exit = sp(t, 68.6, 70.2);
  const c = cam(t);
  const s = c.s * (1 - 0.1 * exit);
  const tx = ANCHOR.x - RIG.left - s * c.fx,
    ty = ANCHOR.y - RIG.top - s * c.fy + (1 - enter) * 160 + exit * 40;
  const ry = (1 - enter) * -16,
    rx = (1 - enter) * 8;

  // station under the needle
  const f = tuneF(t);
  let near = STA[0],
    dist = 99;
  STA.forEach((st) => {
    const d = Math.abs(st.f - f);
    if (d < dist) {
      dist = d;
      near = st;
    }
  });
  const locked = dist < 0.18;
  const stripBlur = motionBlur(((tuneF(t + 0.5 / fps) - tuneF(t - 0.5 / fps)) * fps) * STRIP_PX, fps);
  const auraCol = t < 10 ? station("casual").c : t < 24 ? (locked ? near.c : "#B8B8C0") : NIGHT;

  // screens
  const homeStyle = t >= 58.4 ? show(t, 58.4, null, 0) : show(t, 0, 9.0);
  let playerStyle = show(t, 31.0, 58.2, 40);
  if (t > 58 && t < 58.9) {
    const x = sp(t, 58.2, 58.9);
    playerStyle = { opacity: 1 - x, visibility: "visible", transform: `translateY(${(x * 700).toFixed(1)}px)` };
  }
  const homeTab = t < 9 || t > 58,
    tuneTab = t >= 9 && t < 24;

  // home grids
  const swapOut = eo(p(t, 60.2, 60.8));
  const miniIn = eo(p(t, 58.6, 59.2));

  // tune
  const n = typed(t);
  const caretOn = t > 16.8 && t < 22 && Math.floor(t * 2.2) % 2 === 0;

  // tuning-in wave
  const clean = eo(p(t, 25, 30));
  let wd = "";
  for (let x = 0; x <= 300; x += 3) {
    const nz = Math.sin(x * 0.21 + t * 7.3) * 0.5 + Math.sin(x * 0.53 - t * 5.1) * 0.3 + Math.sin(x * 1.13 + t * 11.7) * 0.2;
    const sn = Math.sin(x * 0.12 - t * 5.0);
    const y = 28 + nz * 20 * (1 - clean) + sn * 12 * (0.3 + 0.7 * clean);
    wd += (x ? "L" : "M") + x + " " + y.toFixed(1);
  }
  const wob = Math.exp(-p(t, 24.2, 25.4) * 4) * Math.sin((t - 24.2) * 20) * 10;

  // player
  const host = t > HOST_IN && t < HOST_OUT;
  const hIn = eo(p(t, HOST_IN, HOST_IN + 0.4)),
    hOut = eo(p(t, HOST_OUT, HOST_OUT + 0.4));
  const idx = Math.min(PROG.host.length - 2, Math.max(0, (t - 36.2) / 1.55));
  const whole = Math.floor(idx),
    frac = eio(clamp((idx - whole) * 3 - 2));
  const pp = lerp(0.12, 0.3, p(t, 31, 58)),
    rd = lerp(0.32, 0.5, p(t, 31, 43)) + 0.16 * eo(p(t, 44, 49.4));
  const secs = Math.max(0, Math.floor(228 + (t - 31) * 12.5));
  const pgT = String(Math.floor(secs / 60)).padStart(2, "0") + ":" + String(secs % 60).padStart(2, "0");
  const rIn = sp(t, 50.2, 50.9),
    rOut = sp(t, 57.2, 57.9);

  // mixer lanes
  const mLevel = 1 - 0.68 * eo(p(t, 35.6, 36.2)) * (1 - eo(p(t, 42.8, 43.6)));
  const hLevel = eo(p(t, 35.8, 36.2)) * (1 - eo(p(t, 42.8, 43.2)));
  let md = "",
    hd = "";
  for (let i = 0; i < 46; i++) {
    const a = (0.35 + 0.65 * Math.abs(Math.sin(i * 0.9 + t * 4.2) * Math.cos(i * 0.37 - t * 2.1))) * 30 * mLevel;
    const b = (0.25 + 0.75 * Math.abs(Math.sin(i * 1.7 + t * 9.1) * Math.sin(i * 0.21 + t * 3.3))) * 30 * hLevel;
    md += "M" + (i * 10 + 4) + " " + (35 - a).toFixed(1) + "V" + (35 + a).toFixed(1);
    hd += "M" + (i * 10 + 4) + " " + (35 - Math.max(0.6, b)).toFixed(1) + "V" + (35 + Math.max(0.6, b)).toFixed(1);
  }

  const capStyle: CSSProperties = { position: "absolute", left: 170, top: 470, width: 820, fontSize: 52, fontWeight: 600, letterSpacing: "-0.02em", lineHeight: 1.25 };
  const routeBg = (i: number) => (i === 0 ? "rgba(255,255,255,.12)" : i === 1 ? "rgba(255,255,255,.05)" : "transparent");
  const routeOp = [1, 1, 0.7, 0.55];

  // key={frame}: a fresh DOM every frame. Chrome otherwise reuses raster tiles
  // across frames and a few anti-aliased pixels differed between two renders;
  // remounting makes repeated renders bit-identical.
  return (
    <>
    <AbsoluteFill key={frame} style={{ background: "#F5F5F7", color: INK, fontFamily: SANS, overflow: "hidden", perspective: 2200 }}>
      <style>{"*,*::before,*::after{box-sizing:border-box}"}</style>
      <div style={abs({ left: 900, top: -160, width: 900, height: 800, borderRadius: "50%", background: auraCol, opacity: t > 24 && t < 58 ? 0.22 : 0.18, filter: "blur(160px)" })} />
      <div style={abs({ left: 260, top: 520, width: 700, height: 600, borderRadius: "50%", background: NIGHT, opacity: 0.1, filter: "blur(160px)" })} />

      {/* captions */}
      {content.captions.map((text, i) => (
        <div key={i} style={{ ...capStyle, ...(i === 4 ? { top: 300 } : null), ...reveal(t, CAPTIONS[i][0], CAPTIONS[i][1]) }}>
          {lines(text)}
        </div>
      ))}

      {/* mixer panel */}
      <div style={{ ...abs({ left: 170, top: 560, width: 620, height: 230, borderRadius: 30, padding: "30px 34px", boxSizing: "border-box" }), ...glass, ...reveal(t, 36.0, 43.0, 30) }}>
        <div style={{ display: "flex", alignItems: "center", gap: 18, height: 70 }}>
          <span style={{ width: 70, fontSize: 22, fontWeight: 600 }}>{content.mixer.music}</span>
          <svg width={460} height={70}>
            <path d={md} stroke={INK} strokeWidth={4} strokeLinecap="round" strokeOpacity={0.75} />
          </svg>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 18, height: 70, marginTop: 24 }}>
          <span style={{ width: 70, fontSize: 22, fontWeight: 600 }}>{content.mixer.host}</span>
          <svg width={460} height={70}>
            <path d={hd} stroke={ACCENT} strokeWidth={4} strokeLinecap="round" />
          </svg>
        </div>
      </div>

      {/* end card */}
      <div style={abs({ left: 0, right: 0, top: 330, display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center" })}>
        <div style={{ width: 150, height: 150, filter: "drop-shadow(0 18px 30px rgba(29,29,31,.18))", ...reveal(t, 70.2, null, 30) }}>
          <div style={{ width: 150, height: 150 }} dangerouslySetInnerHTML={{ __html: LOGO.replace("<svg ", '<svg width="150" height="150" ') }} />
        </div>
        <div style={{ marginTop: 34, fontSize: 96, fontWeight: 600, letterSpacing: "-0.03em", ...reveal(t, 70.7, null, 30) }}>{content.end.name}</div>
        <div style={{ marginTop: 14, fontSize: 40, fontWeight: 500, color: "#86868B", ...reveal(t, 71.3, null, 20) }}>{content.end.line}</div>
        <div style={{ marginTop: 44, fontSize: 28, fontWeight: 500, color: INK, ...reveal(t, 72.0, null, 14) }}>{content.end.url}</div>
      </div>

      {/* phone rig */}
      <div
        style={abs({
          left: RIG.left,
          top: RIG.top,
          width: 410,
          height: 864,
          transformOrigin: "0 0",
          transformStyle: "preserve-3d",
          transform: `translate(${tx.toFixed(1)}px,${ty.toFixed(1)}px) scale(${s.toFixed(4)}) rotateY(${ry.toFixed(2)}deg) rotateX(${rx.toFixed(2)}deg)`,
          opacity: enter * (1 - exit),
        })}
      >
        <div style={abs({ inset: 0, borderRadius: 58, background: INK, padding: 10, boxShadow: "0 50px 100px rgba(29,29,31,.28)" })}>
          <div style={{ position: "relative", width: 390, height: 844, borderRadius: 48, overflow: "hidden", background: "#F2F2F4", color: INK }}>
            {/* HOME */}
            <div style={{ ...abs({ inset: 0, background: "#F2F2F4" }), ...homeStyle }}>
              <div style={abs({ left: -100, top: -160, width: 420, height: 340, borderRadius: "50%", background: t > 58 ? NIGHT : station("lineage").c, opacity: 0.14, filter: "blur(80px)" })} />
              <div style={abs({ left: 20, top: 58, right: 20, display: "flex", justifyContent: "space-between", alignItems: "center" })}>
                <span style={{ fontSize: 34, fontWeight: 700 }}>{content.ui.homeTitle}</span>
                <span style={{ width: 36, height: 36, borderRadius: "50%", background: INK, color: "#fff", display: "grid", placeItems: "center", fontSize: 15, fontWeight: 600 }}>{content.ui.avatar}</span>
              </div>
              <div style={abs({ left: 20, top: 122, fontSize: 22, fontWeight: 700 })}>{content.ui.homeSection}</div>
              <div style={abs({ left: 20, top: 152, fontSize: 13, color: SUB, opacity: eo(p(t, 60.4, 61)) })}>{content.recommendations.because}</div>
              <div style={{ ...gridStyle, opacity: t < 59 ? 1 : 1 - swapOut }}>
                {content.homeCards.map((cd, i) => (
                  <HomeCard key={i} card={cd} build={p(t, 1.4 + i * 0.55, 3.4 + i * 0.55)} />
                ))}
              </div>
              <div style={{ ...gridStyle, opacity: t < 60.4 ? 0 : 1 }}>
                {content.recommendations.cards.map((cd, i) => (
                  <HomeCard key={i} card={cd} build={p(t, 60.6 + i * 0.6, 62.6 + i * 0.6)} textOpacity={eo(p(t, 61.6 + i * 0.6, 62.4 + i * 0.6))} />
                ))}
              </div>
              <div
                style={{
                  ...abs({ left: 10, right: 10, bottom: 92, height: 60, borderRadius: 18, display: "flex", alignItems: "center", gap: 12, padding: "0 14px 0 10px" }),
                  ...glass,
                  background: "rgba(250,250,252,.86)",
                  opacity: t > 58.6 ? miniIn : 0,
                  transform: `translateY(${((1 - miniIn) * 16).toFixed(1)}px)`,
                }}
              >
                <CoverView cv={NOW_BARE} bare style={{ width: 42, height: 42, borderRadius: 8, flexShrink: 0 }} />
                <div style={{ flexGrow: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 15, fontWeight: 600 }}>{PROG.nowPlaying.title}</div>
                  <div style={{ fontSize: 12, color: SUB, display: "flex", alignItems: "center", gap: 6 }}>
                    <span style={{ width: 5, height: 5, borderRadius: "50%", background: ACCENT }} />
                    FM {station(PROG.station).fs} {station(PROG.station).n}
                  </div>
                </div>
                <svg width="22" height="22" viewBox="0 0 24 24" fill={INK}>
                  <rect x="6" y="4.5" width="4" height="15" rx="1.2" />
                  <rect x="14" y="4.5" width="4" height="15" rx="1.2" />
                </svg>
                <span style={abs({ left: 14, right: 14, bottom: 0, height: 2, background: "rgba(29,29,31,.08)" })} />
                <span style={abs({ left: 14, bottom: 0, height: 2, width: `${(pp * 100).toFixed(1)}%`, background: INK })} />
              </div>
            </div>

            {/* TUNE */}
            <div style={{ ...abs({ inset: 0, background: "#F2F2F4" }), ...show(t, 9.0, 24.0) }}>
              <div style={abs({ left: -90, top: -140, width: 460, height: 420, borderRadius: "50%", background: locked ? near.c : "#B8B8C0", opacity: 0.32, filter: "blur(80px)" })} />
              <div style={abs({ left: 20, top: 58, fontSize: 34, fontWeight: 700 })}>{content.ui.tuneTitle}</div>
              <div style={{ ...abs({ left: 20, top: 115, width: 350, height: 300, borderRadius: 28, padding: 20, boxSizing: "border-box" }), ...glass }}>
                <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between" }}>
                  <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
                    <span style={{ fontSize: 15, fontWeight: 500, color: SUB }}>FM</span>
                    <span style={{ fontSize: 56, fontWeight: 200, lineHeight: 1, letterSpacing: "-0.03em", fontVariantNumeric: "tabular-nums" }}>{f.toFixed(1)}</span>
                  </div>
                  <div style={{ display: "flex", alignItems: "flex-end", gap: 3, height: 18, paddingBottom: 8 }}>
                    {[6, 9, 12, 15, 18].map((h, i) => (
                      <span key={i} style={{ width: 4, borderRadius: 1.5, height: h, background: i < (locked ? 5 : 1) ? INK : "rgba(29,29,31,.15)" }} />
                    ))}
                  </div>
                </div>
                <div style={{ marginTop: 12, display: "flex", alignItems: "center", gap: 8, height: 28 }}>
                  <span style={{ fontSize: 20, fontWeight: 600, color: locked ? INK : "#8E8E93" }}>{locked ? near.n : content.ui.betweenStations}</span>
                  <span style={{ fontSize: 12, fontWeight: 500, padding: "3px 8px", borderRadius: 999, background: "rgba(110,98,182,.16)", color: "#4A3F8F", opacity: eo(p(t, 22.3, 22.8)) }}>
                    {content.ui.descChip}
                  </span>
                </div>
                <div style={{ marginTop: 4, fontSize: 15, color: SUB, height: 22 }}>{locked ? near.d : content.ui.betweenHint}</div>
                <div
                  style={abs({
                    left: 20,
                    top: 150,
                    width: 310,
                    height: 96,
                    borderRadius: 18,
                    background: "rgba(226,226,232,.8)",
                    boxShadow: "inset 0 2px 6px rgba(29,29,31,.16),inset 0 1px 1px rgba(29,29,31,.08),0 1px 0 #fff",
                    overflow: "hidden",
                  })}
                >
                  <Dial glow={8}>
                    <Strip x={stripX(f)} blur={stripBlur} id="mb-tune" />
                    <svg width={310} height={96} style={abs({ left: 0, top: 0, opacity: locked ? 0 : Math.min(1, (dist - 0.18) * 2) })}>
                      <path d={NOISE} fill="rgba(29,29,31,.18)" />
                    </svg>
                  </Dial>
                </div>
                <div style={abs({ left: 20, top: 258, width: 310, height: 26, borderRadius: 13, background: "linear-gradient(180deg,rgba(29,29,31,.07),rgba(255,255,255,.75) 50%,rgba(29,29,31,.09))", overflow: "hidden" })}>
                  <svg width={330} height={26} style={{ transform: `translateX(${(-(((f - 84) * 38.75) % 10)).toFixed(2)}px)` }}>
                    {stripBlur > 0.05 ? (
                      <defs>
                        <filter id="mb-knurl" x="-5%" y="0" width="110%" height="100%">
                          <feGaussianBlur stdDeviation={`${stripBlur.toFixed(2)} 0`} />
                        </filter>
                      </defs>
                    ) : null}
                    <path d={KNURL} stroke="rgba(29,29,31,.16)" strokeWidth={1} filter={stripBlur > 0.05 ? "url(#mb-knurl)" : undefined} />
                  </svg>
                </div>
              </div>
              <div style={abs({ left: 20, top: 431, width: 350, height: 56, borderRadius: 16, background: "rgba(255,255,255,.75)", border: ".5px solid rgba(255,255,255,.9)", padding: "0 18px", boxSizing: "border-box", display: "flex", alignItems: "center", fontSize: 17 })}>
                <span style={{ whiteSpace: "nowrap", overflow: "hidden" }}>{content.prompt.slice(0, n)}</span>
                <span style={{ width: 2, height: 22, background: ACCENT, marginLeft: 2, opacity: caretOn ? 1 : 0 }} />
                {n ? null : <span style={abs({ left: 18, color: "#8E8E93" })}>{content.ui.inputPlaceholder}</span>}
              </div>
              <div style={abs({ left: 20, top: 503, width: 350, height: 42, borderRadius: 12, background: "rgba(118,118,128,.12)", display: "grid", gridTemplateColumns: "repeat(3,1fr)", padding: 3, boxSizing: "border-box", fontSize: 14, textAlign: "center", alignItems: "center" })}>
                {content.ui.durations.map((d, i) => (
                  <span key={i} style={i === 1 ? { background: "#fff", borderRadius: 9, height: 36, lineHeight: "36px", fontWeight: 600, boxShadow: "0 2px 6px rgba(0,0,0,.1)" } : undefined}>
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
                  background: INK,
                  color: "#fff",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: 10,
                  fontSize: 17,
                  fontWeight: 600,
                  transform: `scale(${(1 - 0.04 * Math.sin(Math.PI * p(t, 23.0, 23.4))).toFixed(4)})`,
                })}
              >
                <span style={{ width: 8, height: 8, borderRadius: "50%", background: ACCENT, boxShadow: "0 0 0 4px rgba(255,107,44,.25)" }} />
                <span>{locked ? content.ui.ctaLocked.replace("{freq}", near.fs) : content.ui.ctaUnlocked}</span>
              </div>
            </div>

            {/* TUNING-IN */}
            <div style={{ ...abs({ inset: 0, background: "#F2F2F4" }), ...show(t, 24.0, 31.0) }}>
              <div style={abs({ left: -60, top: 80, width: 520, height: 520, borderRadius: "50%", background: NIGHT, opacity: 0.34, filter: "blur(90px)" })} />
              <div style={abs({ left: 20, top: 58, height: 36, padding: "0 14px", borderRadius: 999, background: "rgba(118,118,128,.14)", fontSize: 15, fontWeight: 500, lineHeight: "36px" })}>{content.ui.cancel}</div>
              <div style={{ ...abs({ left: 20, top: 140, width: 350, height: 330, borderRadius: 28, display: "flex", flexDirection: "column", alignItems: "center", paddingTop: 22, boxSizing: "border-box" }), ...glass }}>
                <div style={{ position: "relative", width: 310, height: 96, borderRadius: 18, background: "rgba(226,226,232,.8)", boxShadow: "inset 0 2px 6px rgba(29,29,31,.16),0 1px 0 #fff", overflow: "hidden" }}>
                  <Strip x={stripX(station(PROG.station).f)} id="mb-ti" />
                  <div style={abs({ left: 0, top: 0, bottom: 0, width: 48, background: "linear-gradient(90deg,rgba(228,228,234,.96),rgba(228,228,234,0))" })} />
                  <div style={abs({ right: 0, top: 0, bottom: 0, width: 48, background: "linear-gradient(270deg,rgba(228,228,234,.96),rgba(228,228,234,0))" })} />
                  <div style={abs({ left: 154, top: 8, bottom: 8, width: 2, borderRadius: 1, background: ACCENT, boxShadow: "0 0 10px rgba(255,107,44,.6)", transform: `translateX(${(t < 25.4 ? wob : 0).toFixed(1)}px)` })} />
                </div>
                <div style={{ marginTop: 14, display: "flex", alignItems: "baseline", gap: 6 }}>
                  <span style={{ fontSize: 15, fontWeight: 500, color: SUB }}>FM</span>
                  <span style={{ fontSize: 56, fontWeight: 200, lineHeight: 1, letterSpacing: "-0.03em" }}>{station(PROG.station).fs}</span>
                </div>
                <div style={{ marginTop: 8, fontSize: 20, fontWeight: 600 }}>{station(PROG.station).n}</div>
                <svg width={300} height={56} style={{ marginTop: 14 }}>
                  <path d={wd} fill="none" stroke="#5A4FA0" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </div>
              <div style={abs({ left: 24, top: 500, display: "flex", flexDirection: "column", gap: 14, fontSize: 16 })}>
                {PROG.steps.map((label, i) => {
                  const at = [25.6, 27.2, 28.8][i];
                  const done = t > at + (i === 2 ? 99 : 0),
                    act = t > at - 1.4;
                  const dot: CSSProperties = done
                    ? { background: INK, border: 0, transform: `scale(${(0.6 + 0.4 * eo(p(t, at, at + 0.25))).toFixed(3)})` }
                    : { background: "transparent", border: "1.5px solid rgba(29,29,31,.25)" };
                  return (
                    <div key={i} style={{ display: "flex", alignItems: "center", gap: 12, opacity: act ? 1 : 0.35 }}>
                      <span style={{ width: 22, height: 22, borderRadius: "50%", flexShrink: 0, display: "grid", placeItems: "center", boxSizing: "border-box", ...dot }}>
                        {done ? (
                          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                            <path d="m5 12.5 4.5 4.5L19 7" />
                          </svg>
                        ) : act ? (
                          <span style={{ width: 8, height: 8, borderRadius: "50%", background: ACCENT, opacity: 0.5 + 0.5 * Math.sin(t * 5) }} />
                        ) : null}
                      </span>
                      {label}
                    </div>
                  );
                })}
              </div>
              <div style={abs({ left: 0, right: 0, bottom: 40, textAlign: "center", fontSize: 14, lineHeight: 1.6, color: SUB })}>{lines(content.ui.tuningFootnote)}</div>
            </div>

            {/* PLAYER */}
            <div style={{ ...abs({ inset: 0, background: "#221C2C", color: "#fff" }), ...playerStyle }}>
              <CoverView cv={NOW_BARE} bare style={abs({ left: -160, top: -120, width: 710, height: 710, filter: "blur(70px) saturate(1.3)", opacity: 0.9 })} />
              <div style={abs({ inset: 0, background: "rgba(18,14,26,.45)" })} />
              <div style={abs({ left: 177, top: 58, width: 36, height: 5, borderRadius: 3, background: "rgba(255,255,255,.5)" })} />
              <div style={abs({ left: 24, top: 72, right: 24, height: 44, display: "flex", alignItems: "center", justifyContent: "space-between" })}>
                <span style={roundBtn}>
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="m6 9 6 6 6-6" />
                  </svg>
                </span>
                <span style={{ display: "flex", alignItems: "center", gap: 8, height: 32, padding: "0 14px", borderRadius: 999, background: "rgba(255,255,255,.14)", fontSize: 13, fontWeight: 500 }}>
                  <span style={{ width: 6, height: 6, borderRadius: "50%", background: ACCENT }} />
                  <span style={{ fontWeight: 300 }}>FM {station(PROG.station).fs}</span>
                  <span>{station(PROG.station).n}</span>
                </span>
                <span style={roundBtn}>
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="#fff">
                    <circle cx="5" cy="12" r="1.7" />
                    <circle cx="12" cy="12" r="1.7" />
                    <circle cx="19" cy="12" r="1.7" />
                  </svg>
                </span>
              </div>
              <CoverView cv={NOW} style={abs({ left: 47, top: 136, width: 296, height: 296, borderRadius: 12, boxShadow: "0 22px 50px rgba(0,0,0,.4)" })} />
              <div style={abs({ left: 24, top: 452, right: 24 })}>
                <div style={{ fontSize: 22, fontWeight: 600 }}>{PROG.nowPlaying.title}</div>
                <div style={{ fontSize: 19, color: "rgba(255,255,255,.62)" }}>{PROG.nowPlaying.artist}</div>
              </div>
              <div style={abs({ left: 24, right: 24, top: 520, height: 92, borderRadius: 18, background: "rgba(255,255,255,.13)", overflow: "hidden" })}>
                <div style={abs({ left: 14, right: 14, top: 12, opacity: 1 - hIn * (1 - hOut) })}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: "rgba(255,255,255,.8)", display: "flex", gap: 8, alignItems: "center" }}>
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="#fff">
                      <path d="M5 4.5v15l12-7.5z" />
                    </svg>
                    {content.ui.upNext}
                  </div>
                  <div style={{ marginTop: 6, fontSize: 15 }}>{PROG.upNext.track}</div>
                  <div style={{ fontSize: 13, color: "rgba(255,255,255,.55)" }}>{PROG.upNext.chapter}</div>
                </div>
                <div style={abs({ left: 14, right: 14, top: 12, opacity: hIn * (1 - hOut) })}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: "rgba(255,255,255,.8)", display: "flex", gap: 8, alignItems: "center" }}>
                    <span style={{ display: "flex", gap: 2, alignItems: "center", height: 12 }}>
                      {[0, 1, 2, 3, 4].map((i) => (
                        <span key={i} style={{ width: 2.5, borderRadius: 1, background: "#fff", height: host ? 3 + 9 * Math.abs(Math.sin(t * (6 + i * 1.7) + i)) : 3 }} />
                      ))}
                    </span>
                    {content.ui.hostSpeaking}
                    <span style={{ marginLeft: "auto", fontWeight: 400, color: "rgba(255,255,255,.6)", fontSize: 12 }}>{content.ui.fullText}</span>
                  </div>
                  <div style={{ position: "relative", marginTop: 6, height: 45, overflow: "hidden", maskImage: "linear-gradient(180deg,transparent 0,#000 9px)", WebkitMaskImage: "linear-gradient(180deg,transparent 0,#000 9px)" }}>
                    <div style={abs({ left: 0, right: 0, top: 0, fontSize: 15, lineHeight: "22.5px", transform: `translateY(${(-(whole + frac) * 22.5).toFixed(2)}px)` })}>
                      {PROG.host.map((l, i) => (
                        <div key={i}>{l}</div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
              <div style={abs({ left: 24, right: 24, top: 630 })}>
                <div style={{ position: "relative", height: 6, borderRadius: 3, background: "repeating-linear-gradient(90deg,rgba(255,255,255,.22) 0 3px,transparent 3px 7px)", overflow: "hidden" }}>
                  <span style={abs({ left: 0, top: 0, bottom: 0, width: `${(rd * 100).toFixed(2)}%`, background: "rgba(255,255,255,.34)" })} />
                  <span style={abs({ left: 0, top: 0, bottom: 0, width: `${(pp * 100).toFixed(2)}%`, background: "#fff" })} />
                </div>
                <div style={{ marginTop: 8, display: "flex", justifyContent: "space-between", fontSize: 12, color: "rgba(255,255,255,.6)", fontVariantNumeric: "tabular-nums" }}>
                  <span>{pgT}</span>
                  <span>{PROG.durationLabel}</span>
                </div>
              </div>
              <div style={abs({ left: 46, right: 46, top: 672, height: 72, display: "flex", alignItems: "center", justifyContent: "space-between" })}>
                <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3" />
                  <path d="M4.5 3.8v3.7h3.7" />
                  <text x="12.4" y="15.4" textAnchor="middle" fontSize="7" fontWeight="600" fill="#fff" stroke="none">
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
                <span style={{ width: 44, height: 44, borderRadius: 12, display: "grid", placeItems: "center" }}>
                  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="rgba(255,255,255,.8)" strokeWidth="1.8" strokeLinecap="round">
                    <path d="M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01" />
                  </svg>
                </span>
              </div>

              {/* route sheet */}
              <div
                style={abs({
                  left: 0,
                  right: 0,
                  bottom: 0,
                  height: 600,
                  borderRadius: "28px 28px 0 0",
                  background: "rgba(36,30,48,.82)",
                  backdropFilter: "blur(40px) saturate(1.4)",
                  borderTop: ".5px solid rgba(255,255,255,.18)",
                  padding: "10px 20px 34px",
                  boxSizing: "border-box",
                  transform: `translateY(${((1 - rIn) * 620 + rOut * 620).toFixed(1)}px)`,
                })}
              >
                <div style={{ width: 36, height: 5, borderRadius: 3, background: "rgba(255,255,255,.35)", margin: "0 auto" }} />
                <div style={{ marginTop: 14, fontSize: 22, fontWeight: 700 }}>{content.ui.routeTitle}</div>
                <div style={{ fontSize: 13, color: "rgba(255,255,255,.6)" }}>{PROG.routeSubtitle}</div>
                <div style={{ marginTop: 18, display: "flex", flexDirection: "column", gap: 6 }}>
                  {PROG.route.map((ch, i) => (
                    <div
                      key={i}
                      style={{
                        borderRadius: 16,
                        padding: "12px 14px",
                        background: routeBg(i),
                        opacity: routeOp[Math.min(i, routeOp.length - 1)],
                        transform: `translateY(${((1 - eo(p(t, 50.6 + i * 0.15, 51.2 + i * 0.15))) * 20).toFixed(1)}px)`,
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <span>
                          <span style={{ fontSize: 13, fontWeight: 300, color: "rgba(255,255,255,.6)", marginRight: 8 }}>{ch.at}</span>
                          <span style={{ fontSize: 16, fontWeight: 600 }}>{ch.title}</span>
                        </span>
                        <span style={{ fontSize: 12, fontWeight: 500, color: i === 0 ? "#FF8A55" : "rgba(255,255,255,.55)" }}>{ch.status}</span>
                      </div>
                      {ch.tracks.map((tr, j) => (
                        <div key={j} style={{ marginTop: 8, fontSize: 14, color: tr.state === "playing" ? "#fff" : tr.state === "pending" ? "rgba(255,255,255,.5)" : "rgba(255,255,255,.78)", display: "flex", gap: 10, alignItems: "center" }}>
                          <span style={{ width: 14, display: "flex", gap: 1.5, alignItems: "flex-end", height: 12 }}>
                            {tr.state === "playing"
                              ? [6, 12, 8].map((h, k) => <span key={k} style={{ width: 3, height: h, background: ACCENT }} />)
                              : null}
                          </span>
                          {tr.name}
                        </div>
                      ))}
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* tab bar (home / tune) */}
            <div
              style={abs({
                left: 0,
                right: 0,
                bottom: 0,
                height: 84,
                background: "rgba(242,242,244,.86)",
                backdropFilter: "blur(24px)",
                borderTop: ".5px solid rgba(60,60,67,.18)",
                display: "grid",
                gridTemplateColumns: "repeat(3,1fr)",
                padding: "10px 24px 26px",
                boxSizing: "border-box",
                fontSize: 11,
                textAlign: "center",
                opacity: t < 24 || t > 58.4 ? 1 : 0,
              })}
            >
              {content.ui.tabs.map((label, i) => {
                const on = (i === 0 && homeTab) || (i === 1 && tuneTab);
                return (
                  <span key={i} style={{ fontWeight: on ? 600 : 400, color: on ? INK : "#8E8E93" }}>
                    {label}
                  </span>
                );
              })}
            </div>

            <div
              style={{
                ...abs({ left: 0, top: 0, width: 46, height: 46, margin: "-23px 0 0 -23px", borderRadius: "50%", background: "rgba(255,255,255,.55)", border: "1.5px solid rgba(255,255,255,.9)", boxShadow: "0 4px 14px rgba(0,0,0,.18)", boxSizing: "border-box" }),
                ...fingerStyle(t, fps),
              }}
            />
          </div>
        </div>
      </div>

      <div style={abs({ inset: 0, background: "#000", opacity: fade })} />
    </AbsoluteFill>
    {sfx ? <Sfx /> : null}
    </>
  );
}

const gridStyle: CSSProperties = { position: "absolute", left: 20, top: 176, width: 350, display: "grid", gridTemplateColumns: "165px 165px", gap: "18px 20px" };
const roundBtn: CSSProperties = { width: 40, height: 40, borderRadius: "50%", background: "rgba(255,255,255,.14)", display: "grid", placeItems: "center" };
