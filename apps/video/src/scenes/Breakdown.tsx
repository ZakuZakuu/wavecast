import { BREAKDOWN } from "../content";
import { SANS } from "../fonts";
import { clamp, eio, eo, lerp, p } from "../lib/math";
import { AFTERNOON } from "../timeline";
import { breakdownPose } from "./Phone";

const COL_X = 1290;
const COL_W = 540;
const GAP = 14;
const H = (i: number) => (BREAKDOWN[i].visual ? 126 : 108);
const TOPS = (() => {
  const total = BREAKDOWN.reduce((a, _, i) => a + H(i), 0) + GAP * (BREAKDOWN.length - 1);
  let y = 540 - total / 2;
  return BREAKDOWN.map((_, i) => {
    const top = y;
    y += H(i) + GAP;
    return top;
  });
})();
const ORIGIN = { x: 1030, y: 540 };

function Voice({ t, on }: { t: number; on: number }) {
  let d = "";
  for (let x = 0; x <= 480; x += 4) {
    const env = Math.sin((x / 480) * Math.PI);
    const y = 22 + env * on * (Math.sin(x * 0.07 - t * 6) * 9 + Math.sin(x * 0.19 + t * 4.3) * 5);
    d += `${x ? "L" : "M"}${x} ${y.toFixed(1)}`;
  }
  return (
    <svg width={480} height={44} style={{ display: "block", marginTop: 10 }}>
      <path d={d} fill="none" stroke="#FF6B2C" strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function Mix({ t, on }: { t: number; on: number }) {
  let md = "";
  let hd = "";
  for (let i = 0; i < 40; i++) {
    const a = (0.35 + 0.65 * Math.abs(Math.sin(i * 0.9 + t * 4.2) * Math.cos(i * 0.37 - t * 2.1))) * 9 * (0.4 + 0.6 * on);
    const b = (0.25 + 0.75 * Math.abs(Math.sin(i * 1.7 + t * 9.1) * Math.sin(i * 0.21 + t * 3.3))) * 9 * on;
    md += `M${i * 12 + 3} ${(11 - a).toFixed(1)}V${(11 + a).toFixed(1)}`;
    hd += `M${i * 12 + 3} ${(33 - Math.max(0.6, b)).toFixed(1)}V${(33 + Math.max(0.6, b)).toFixed(1)}`;
  }
  return (
    <svg width={480} height={44} style={{ display: "block", marginTop: 10 }}>
      <path d={md} stroke="#1D1D1F" strokeOpacity={0.7} strokeWidth={3.5} strokeLinecap="round" />
      <path d={hd} stroke="#FF6B2C" strokeWidth={3.5} strokeLinecap="round" />
    </svg>
  );
}

/** 幕后拆解: the screen comes apart into layers that light up one by one. */
export function Breakdown({ t }: { t: number }) {
  const [b0, b1] = AFTERNOON.breakdown;
  if (t < b0 || t > b1) return null;
  const pose = breakdownPose(t);
  const back = eio(p(t, AFTERNOON.collapse[0], AFTERNOON.collapse[0] + 0.9));
  return (
    <div style={{ position: "absolute", inset: 0, perspective: 2200, perspectiveOrigin: "50% 50%", fontFamily: SANS }}>
      {BREAKDOWN.map((c, i) => {
        // Peel off the screen with a small stagger, travel back and out to the column.
        const out = eo(p(t, AFTERNOON.explode[0] + 0.3 + i * 0.12, AFTERNOON.explode[0] + 1.3 + i * 0.12));
        const ret = eio(p(t, AFTERNOON.collapse[0] + (5 - i) * 0.06, AFTERNOON.collapse[0] + 0.7 + (5 - i) * 0.06));
        const k = out * (1 - ret);
        if (k < 0.002) return null;
        const litAt = AFTERNOON.cardsLit + i * AFTERNOON.cardStep;
        const lit = eo(p(t, litAt, litAt + 0.45));
        const x = lerp(ORIGIN.x - COL_W / 2, COL_X, k);
        const y = lerp(ORIGIN.y - H(i) / 2, TOPS[i], k);
        const z = lerp(0, -40 - i * 36, k);
        const s = lerp(0.55, 1, k);
        return (
          <div
            key={c.title}
            style={{
              position: "absolute",
              left: x,
              top: y,
              width: COL_W,
              height: H(i),
              boxSizing: "border-box",
              padding: "18px 26px",
              borderRadius: 22,
              background: `rgba(255,255,255,${lerp(0.38, 0.7, lit).toFixed(3)})`,
              border: ".5px solid rgba(255,255,255,.9)",
              boxShadow: `0 16px 40px rgba(29,60,55,${lerp(0.06, 0.14, lit).toFixed(3)})`,
              backdropFilter: "blur(24px)",
              opacity: k * clamp(1 - back * 0) * lerp(0.55, 1, lit) * clamp(pose * 2),
              transform: `translateZ(${z.toFixed(1)}px) rotateY(${(18 * pose).toFixed(2)}deg) scale(${s.toFixed(4)})`,
              transformOrigin: "0 50%",
              color: "#1D1D1F",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <span
                style={{
                  width: 10,
                  height: 10,
                  borderRadius: "50%",
                  background: lit > 0.5 ? "#FF6B2C" : "rgba(29,29,31,.2)",
                  boxShadow: `0 0 ${(12 * lit).toFixed(1)}px rgba(255,107,44,${(0.7 * lit).toFixed(2)})`,
                }}
              />
              <span style={{ fontSize: 26, fontWeight: 600 }}>{c.title}</span>
            </div>
            {c.body ? <div style={{ marginTop: 10, marginLeft: 22, fontSize: 21, color: "#3A3A3C", whiteSpace: "nowrap" }}>{c.body}</div> : null}
            {c.visual === "voice" ? <div style={{ marginLeft: 22 }}><Voice t={t} on={lit} /></div> : null}
            {c.visual === "mix" ? <div style={{ marginLeft: 22 }}><Mix t={t} on={lit} /></div> : null}
          </div>
        );
      })}
    </div>
  );
}
