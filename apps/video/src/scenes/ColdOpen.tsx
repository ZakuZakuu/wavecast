import { AbsoluteFill } from "remotion";
import { BRAND } from "../content";
import { SANS } from "../fonts";
import { clamp, env, eo, p } from "../lib/math";
import { STATIONS, stationById } from "../stations";
import { COLD } from "../timeline";
import { coldFreq, STATION_HITS } from "./coldCurve";

const BASE_Y = 560;
const X0 = 160;
const X1 = 1760;
const F0 = 86;
const F1 = 108;
const fx = (f: number) => X0 + ((f - F0) / (F1 - F0)) * (X1 - X0);

function ticksPath() {
  // 0.2 MHz ticks; integers are tall, every half-MHz gets a mid-height mark.
  let major = "";
  let half = "";
  let minor = "";
  for (let i = F0 * 5; i <= F1 * 5; i++) {
    const x = fx(i / 5).toFixed(1);
    if (i % 5 === 0) major += `M${x} ${BASE_Y - 46}V${BASE_Y}`;
    else minor += `M${x} ${BASE_Y - 14}V${BASE_Y}`;
  }
  for (let f = F0 + 0.5; f < F1; f += 1) half += `M${fx(f).toFixed(1)} ${BASE_Y - 28}V${BASE_Y}`;
  return { major, half, minor };
}
const TICKS = ticksPath();

export function ColdOpen({ t }: { t: number }) {
  if (t > COLD.dawn[1] + 0.1) return null;
  const f = coldFreq(t);
  const nx = fx(f);
  // Dial lights up left to right between 0.4 and 1.2 s, fades as the brand arrives.
  const dialOut = 1 - eo(p(t, COLD.dialOut[0], COLD.dialOut[1]));
  const dialIn = (x: number) => eo(clamp(((t - COLD.dialIn[0]) / (COLD.dialIn[1] - COLD.dialIn[0])) * 1.6 - ((x - X0) / (X1 - X0)) * 0.6));
  const needleIn = eo(p(t, 0.9, 1.3));
  const lockFlash = env(t, COLD.lock[0] + 0.05, COLD.lock[0] + 0.5, 0.25, 0.8);

  // Station glow: strongest when the needle sits on it.
  const glows = STATIONS.map((s) => clamp(1 - Math.abs(s.freq - f) / 0.9));
  const hit = STATION_HITS.map((h) => {
    const s = STATIONS.find((st) => st.freq === h.freq)!;
    const last = h.freq === COLD.lockFreq;
    const op = env(t, h.at - 0.12, last ? COLD.dialOut[0] : h.until + 0.05, 0.3, 0.45);
    return { s, op, x: fx(h.freq) };
  });
  const near = STATIONS.reduce((best, s, i) => (glows[i] > best.g ? { g: glows[i], c: s.light } : best), { g: 0, c: "#FF6B2C" });

  const brand = env(t, COLD.brandIn, COLD.brandOut, 0.9, 0.7);
  const tag = env(t, COLD.brandIn + 0.35, COLD.brandOut, 0.9, 0.7);

  return (
    <AbsoluteFill style={{ fontFamily: SANS, color: "#F5F5F7" }}>
      <div style={{ position: "absolute", inset: 0, opacity: dialOut }}>
        {/* Station-coloured bloom around the needle */}
        <div
          style={{
            position: "absolute",
            left: nx - 260,
            top: BASE_Y - 330,
            width: 520,
            height: 460,
            borderRadius: "50%",
            background: near.c,
            opacity: 0.32 * near.g * needleIn,
            filter: "blur(90px)",
          }}
        />
        <svg width={1920} height={1080} style={{ position: "absolute", inset: 0 }}>
          <defs>
            <linearGradient id="reveal" x1="0" x2="1">
              <stop offset="0" stopColor="#fff" stopOpacity={dialIn(X0)} />
              <stop offset="0.5" stopColor="#fff" stopOpacity={dialIn((X0 + X1) / 2)} />
              <stop offset="1" stopColor="#fff" stopOpacity={dialIn(X1)} />
            </linearGradient>
            <mask id="dialmask">
              <rect x={0} y={0} width={1920} height={1080} fill="url(#reveal)" />
            </mask>
          </defs>
          <g mask="url(#dialmask)">
            <path d={TICKS.minor} stroke="rgba(245,245,247,.28)" strokeWidth={1.4} strokeLinecap="round" />
            <path d={TICKS.half} stroke="rgba(245,245,247,.45)" strokeWidth={1.6} strokeLinecap="round" />
            <path d={TICKS.major} stroke="rgba(245,245,247,.7)" strokeWidth={2} strokeLinecap="round" />
            {Array.from({ length: (F1 - F0) / 2 + 1 }, (_, i) => F0 + i * 2).map((n) => (
              <text key={n} x={fx(n)} y={BASE_Y + 44} textAnchor="middle" fontSize={26} fontWeight={300} fill="rgba(245,245,247,.55)" style={{ fontFamily: SANS, fontVariantNumeric: "tabular-nums" }}>
                {n}
              </text>
            ))}
            {STATIONS.map((s, i) => (
              <circle key={s.id} cx={fx(s.freq)} cy={BASE_Y - 74} r={6 + 3 * glows[i]} fill={s.light} />
            ))}
          </g>
        </svg>
        {/* Needle */}
        <div
          style={{
            position: "absolute",
            left: nx - 1.5,
            top: BASE_Y - 160,
            width: 3,
            height: 220,
            borderRadius: 2,
            background: "#FF6B2C",
            boxShadow: `0 0 ${14 + 26 * lockFlash}px rgba(255,107,44,${(0.75 + 0.25 * lockFlash).toFixed(2)}), 0 0 4px rgba(255,140,90,.9)`,
            opacity: needleIn,
          }}
        />
        {/* Station names under the dial */}
        {hit.map(({ s, op, x }) =>
          op > 0.002 ? (
            <div
              key={s.id}
              style={{
                position: "absolute",
                left: x - 200,
                width: 400,
                top: BASE_Y + 92,
                textAlign: "center",
                fontSize: 30,
                fontWeight: 300,
                letterSpacing: "0.32em",
                textIndent: "0.32em",
                color: "#F5F5F7",
                opacity: op,
                transform: `translateY(${((1 - op) * 10).toFixed(1)}px)`,
                filter: `blur(${((1 - op) * 6).toFixed(1)}px)`,
              }}
            >
              {stationById(s.id).name}
            </div>
          ) : null,
        )}
      </div>

      {/* Brand */}
      <div style={{ position: "absolute", left: 0, right: 0, top: 404, textAlign: "center" }}>
        <div style={{ fontSize: 150, fontWeight: 600, letterSpacing: "-0.03em", lineHeight: 1.1, opacity: brand, transform: `translateY(${((1 - brand) * 20).toFixed(1)}px)`, filter: `blur(${((1 - brand) * 10).toFixed(1)}px)` }}>
          {BRAND.name}
        </div>
        <div style={{ marginTop: 22, fontSize: 40, fontWeight: 300, color: "rgba(245,245,247,.78)", opacity: tag, transform: `translateY(${((1 - tag) * 20).toFixed(1)}px)`, filter: `blur(${((1 - tag) * 10).toFixed(1)}px)` }}>
          {BRAND.tagline}
        </div>
      </div>
    </AbsoluteFill>
  );
}
