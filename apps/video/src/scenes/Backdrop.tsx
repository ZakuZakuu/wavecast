import { AbsoluteFill } from "remotion";
import { light } from "../scene";
import { AFTERNOON, NIGHT } from "../timeline";
import { clamp, eio, mixHex, p, rng } from "../lib/math";
import { nearestStation } from "../stations";
import { tuneFreq } from "./afternoonCurve";

const W = 1920;
const H = 1080;

/* ---------- morning: apricot light, slanted beams, dust ---------- */
const DUST = (() => {
  const R = rng(4011);
  return Array.from({ length: 46 }, () => ({ x: R() * W, y: R() * H, r: 1 + R() * 2.6, vx: -6 + R() * 12, vy: -10 + R() * 6, ph: R() * 6.28, o: 0.25 + R() * 0.5 }));
})();

function Morning({ t, o }: { t: number; o: number }) {
  if (o <= 0.002) return null;
  return (
    <AbsoluteFill style={{ opacity: o, background: "radial-gradient(120% 110% at 18% 8%, #F7D6B4 0%, #F9E6D0 38%, #FBF4EA 70%, #FCF8F2 100%)" }}>
      {[0, 1, 2, 3].map((i) => {
        const drift = Math.sin(t * 0.13 + i * 1.7) * 60;
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: -200 + i * 430 + drift,
              top: -300,
              width: 150 + i * 40,
              height: 1800,
              transform: "rotate(28deg)",
              transformOrigin: "50% 0",
              background: "linear-gradient(180deg, rgba(255,236,206,.55), rgba(255,236,206,0) 80%)",
              filter: "blur(30px)",
              opacity: 0.55 + 0.25 * Math.sin(t * 0.21 + i),
            }}
          />
        );
      })}
      <svg width={W} height={H} style={{ position: "absolute", inset: 0 }}>
        {DUST.map((d, i) => {
          const x = (((d.x + d.vx * t + Math.sin(t * 0.4 + d.ph) * 14) % W) + W) % W;
          const y = (((d.y + d.vy * t) % H) + H) % H;
          return <circle key={i} cx={x} cy={y} r={d.r} fill="#FFF6E8" opacity={d.o * (0.6 + 0.4 * Math.sin(t * 0.9 + d.ph))} />;
        })}
      </svg>
    </AbsoluteFill>
  );
}

/* ---------- afternoon: clear teal light, dappled leaf shade, station tint ---------- */
const DAPPLE = (() => {
  const R = rng(733);
  return Array.from({ length: 16 }, () => ({ x: R() * W, y: R() * H, r: 140 + R() * 220, ph: R() * 6.28, sp: 0.2 + R() * 0.25 }));
})();

function tint(t: number) {
  const f = tuneFreq(t);
  const { station, dist } = nearestStation(f);
  const locked = clamp(1 - (dist - 0.12) / 0.5);
  const color = mixHex("#B8B8C0", station.light, locked);
  const strength = eio(p(t, AFTERNOON.drag[0] - 0.4, AFTERNOON.drag[0] + 0.2)) * (1 - eio(p(t, AFTERNOON.ctaTap[1], AFTERNOON.ctaTap[1] + 1.2)));
  return { color, strength };
}

function Afternoon({ t, o }: { t: number; o: number }) {
  if (o <= 0.002) return null;
  const tn = tint(t);
  return (
    <AbsoluteFill style={{ opacity: o, background: "radial-gradient(130% 110% at 75% 10%, #CFEDE6 0%, #E4F4F0 40%, #F6FBFA 78%, #FBFDFD 100%)" }}>
      <AbsoluteFill style={{ background: `radial-gradient(90% 80% at 62% 45%, ${tn.color} 0%, transparent 70%)`, opacity: 0.55 * tn.strength }} />
      {DAPPLE.map((d, i) => {
        const x = d.x + Math.sin(t * d.sp + d.ph) * 40;
        const y = d.y + Math.cos(t * d.sp * 0.8 + d.ph) * 26;
        return (
          <div
            key={i}
            style={{ position: "absolute", left: x - d.r, top: y - d.r, width: d.r * 2, height: d.r * 1.6, borderRadius: "50%", background: "#2F6F63", opacity: 0.055, filter: "blur(60px)" }}
          />
        );
      })}
    </AbsoluteFill>
  );
}

/* ---------- night: rain, distant bokeh, drops on the glass ---------- */
const RAIN = (() => {
  const R = rng(9001);
  return Array.from({ length: 220 }, () => ({ x: R() * (W + 300) - 300, y: R() * H, len: 40 + R() * 90, w: 0.8 + R() * 1.2, v: 900 + R() * 700, a: 0.05 + R() * 0.14 }));
})();
const BOKEH_COLORS = ["255,170,90", "255,214,130", "150,190,255", "190,160,255", "255,120,80"];
const BOKEH = (() => {
  const R = rng(1207);
  return Array.from({ length: 34 }, () => ({
    x: R() * W,
    y: 120 + R() * (H - 240),
    r: 18 + R() * 70,
    c: BOKEH_COLORS[Math.floor(R() * BOKEH_COLORS.length)],
    o: 0.05 + R() * 0.12,
    ph: R() * 6.28,
    sp: 0.15 + R() * 0.3,
  }));
})();
const DROPS = (() => {
  const R = rng(321);
  return Array.from({ length: 26 }, () => ({ x: R() * W, y: R() * H, r: 3 + R() * 7, v: 6 + R() * 18, ph: R() * 6.28 }));
})();

function Night({ t, o }: { t: number; o: number }) {
  if (o <= 0.002) return null;
  const rain = eio(p(t, NIGHT.rainIn[0], NIGHT.rainIn[1])) * (1 - eio(p(t, NIGHT.rainOut[0], NIGHT.rainOut[1])));
  return (
    <AbsoluteFill style={{ opacity: o, background: "radial-gradient(120% 90% at 70% 40%, #1B1C38 0%, #0D1224 55%, #070A14 100%)" }}>
      {BOKEH.map((b, i) => {
        const breathe = 0.75 + 0.25 * Math.sin(t * b.sp * 2 + b.ph);
        const x = b.x + Math.sin(t * b.sp + b.ph) * 18;
        const y = b.y + Math.cos(t * b.sp * 0.7 + b.ph) * 10;
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: x - b.r,
              top: y - b.r,
              width: b.r * 2,
              height: b.r * 2,
              borderRadius: "50%",
              background: `radial-gradient(circle, rgba(${b.c},1) 0%, rgba(${b.c},.55) 45%, rgba(${b.c},0) 72%)`,
              opacity: b.o * breathe,
            }}
          />
        );
      })}
      <svg width={W} height={H} style={{ position: "absolute", inset: 0, opacity: rain }}>
        {RAIN.map((r, i) => {
          const span = H + r.len;
          const y = ((r.y + r.v * t) % span) - r.len;
          const x = r.x + (y + r.len) * 0.18;
          return <line key={i} x1={x} y1={y} x2={x + r.len * 0.18} y2={y + r.len} stroke={`rgba(210,220,255,${r.a.toFixed(3)})`} strokeWidth={r.w} strokeLinecap="round" />;
        })}
      </svg>
      <svg width={W} height={H} style={{ position: "absolute", inset: 0, opacity: rain }}>
        {DROPS.map((d, i) => {
          const y = (d.y + d.v * t) % (H + 20);
          const x = d.x + Math.sin(t * 0.3 + d.ph) * 2;
          return (
            <g key={i}>
              <ellipse cx={x} cy={y} rx={d.r * 0.9} ry={d.r} fill="rgba(200,212,255,.10)" stroke="rgba(220,230,255,.18)" strokeWidth={0.8} />
              <circle cx={x - d.r * 0.3} cy={y - d.r * 0.35} r={Math.max(0.8, d.r * 0.22)} fill="rgba(255,255,255,.5)" />
            </g>
          );
        })}
      </svg>
    </AbsoluteFill>
  );
}

export function Backdrop({ t }: { t: number }) {
  const l = light(t);
  return (
    <AbsoluteFill style={{ background: "#000" }}>
      {/* Crossfades keep the lower layer opaque so no black shows through. */}
      <Morning t={t} o={l.black > 0 ? l.morning : l.morning > 0 || (l.afternoon > 0 && l.afternoon < 1) ? 1 : 0} />
      <Afternoon t={t} o={l.afternoon > 0 ? (l.night > 0 ? 1 : l.afternoon) : 0} />
      <Night t={t} o={l.night} />
    </AbsoluteFill>
  );
}
