import { HOST, MIXER } from "../content";
import { SANS } from "../fonts";
import { eo, p } from "../lib/math";
import { NIGHT } from "../timeline";
import { MARGIN_X, Subtitle, textIn } from "./Text";

/** Host lines as film subtitles, ~1.8 s each. */
export function HostSubtitles({ t }: { t: number }) {
  const [h0] = NIGHT.host;
  return (
    <>
      {HOST.map((line, i) => {
        const at = h0 + i * NIGHT.hostLine;
        if (t < at - 0.1 || t > at + NIGHT.hostLine + 0.5) return null;
        return <Subtitle key={line} t={t} text={line} style={textIn(t, at, at + NIGHT.hostLine - 0.35, 0.4, 0.35)} />;
      })}
    </>
  );
}

/** Mixer: music ducks to ~30% while the orange host lane rises. */
export function Mixer({ t }: { t: number }) {
  const [m0, m1] = NIGHT.mixer;
  if (t < m0 - 0.1 || t > m1 + 1) return null;
  const [h0, h1] = NIGHT.host;
  const mLevel = 1 - 0.7 * eo(p(t, h0 - 0.1, h0 + 0.5)) * (1 - eo(p(t, h1, h1 + 0.6)));
  const hLevel = eo(p(t, h0, h0 + 0.4)) * (1 - eo(p(t, h1, h1 + 0.4)));
  let md = "";
  let hd = "";
  for (let i = 0; i < 46; i++) {
    const a = (0.35 + 0.65 * Math.abs(Math.sin(i * 0.9 + t * 4.2) * Math.cos(i * 0.37 - t * 2.1))) * 30 * mLevel;
    const b = (0.25 + 0.75 * Math.abs(Math.sin(i * 1.7 + t * 9.1) * Math.sin(i * 0.21 + t * 3.3))) * 30 * hLevel;
    md += `M${i * 10 + 4} ${(35 - a).toFixed(1)}V${(35 + a).toFixed(1)}`;
    hd += `M${i * 10 + 4} ${(35 - Math.max(0.6, b)).toFixed(1)}V${(35 + Math.max(0.6, b)).toFixed(1)}`;
  }
  const st = textIn(t, m0, m1, 0.8, 0.6);
  const { op, ...style } = st;
  if (op < 0.002) return null;
  return (
    <div
      style={{
        position: "absolute",
        left: MARGIN_X,
        top: 540,
        width: 620,
        height: 230,
        boxSizing: "border-box",
        borderRadius: 30,
        padding: "30px 34px",
        background: "rgba(255,255,255,.08)",
        border: ".5px solid rgba(255,255,255,.18)",
        boxShadow: "0 20px 50px rgba(0,0,0,.25)",
        backdropFilter: "blur(30px)",
        color: "#F5F5F7",
        fontFamily: SANS,
        ...style,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 18, height: 70 }}>
        <span style={{ width: 70, fontSize: 22, fontWeight: 600 }}>{MIXER.music}</span>
        <svg width={460} height={70}>
          <path d={md} stroke="#F5F5F7" strokeOpacity={0.75} strokeWidth={4} strokeLinecap="round" />
        </svg>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 18, height: 70, marginTop: 24 }}>
        <span style={{ width: 70, fontSize: 22, fontWeight: 600 }}>{MIXER.host}</span>
        <svg width={460} height={70}>
          <path d={hd} stroke="#FF6B2C" strokeWidth={4} strokeLinecap="round" />
        </svg>
      </div>
    </div>
  );
}
