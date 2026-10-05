import { useLayoutEffect, useRef } from "react";
import { AbsoluteFill } from "remotion";
import { BRAND } from "../content";
import { darkness } from "../scene";
import { END, HEIGHT, WIDTH } from "../timeline";
import { ei, lerp, p, rng } from "../lib/math";
import { SANS } from "../fonts";

/** Film grain: refreshed 24 times a second, seeded by the grain frame number. */
export function Grain({ t }: { t: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const grainFrame = Math.floor(t * 24);
  useLayoutEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const w = WIDTH / 2;
    const h = HEIGHT / 2;
    const img = ctx.createImageData(w, h);
    const data = new Uint32Array(img.data.buffer);
    const R = rng(0x9e3779b1 ^ (grainFrame * 2654435761));
    for (let i = 0; i < data.length; i++) {
      const v = (R() * 255) | 0;
      data[i] = (255 << 24) | (v << 16) | (v << 8) | v;
    }
    ctx.putImageData(img, 0, 0);
  }, [grainFrame]);
  return (
    <canvas
      ref={ref}
      width={WIDTH / 2}
      height={HEIGHT / 2}
      style={{ position: "absolute", inset: 0, width: WIDTH, height: HEIGHT, mixBlendMode: "overlay", opacity: 0.07, pointerEvents: "none" }}
    />
  );
}

export function Vignette({ t }: { t: number }) {
  const strength = lerp(0.2, 0.45, darkness(t));
  return (
    <AbsoluteFill
      style={{ background: `radial-gradient(120% 100% at 50% 50%, transparent 60%, rgba(0,0,0,${strength.toFixed(3)}) 100%)`, pointerEvents: "none" }}
    />
  );
}

export function Disclaimer({ t }: { t: number }) {
  const d = darkness(t);
  // Blend from #86868B (light scenes) to rgba(255,255,255,.42) (dark scenes).
  const r = Math.round(lerp(0x86, 255, d));
  const g = Math.round(lerp(0x86, 255, d));
  const b = Math.round(lerp(0x8b, 255, d));
  const a = lerp(1, 0.42, d);
  return (
    <div style={{ position: "absolute", right: 40, bottom: 32, fontFamily: SANS, fontSize: 18, fontWeight: 400, color: `rgba(${r},${g},${b},${a.toFixed(3)})`, whiteSpace: "nowrap" }}>
      {BRAND.disclaimer}
    </div>
  );
}

/** Final fade to black (takes the disclaimer with it). */
export function FadeOut({ t }: { t: number }) {
  const o = ei(p(t, END.fade[0], END.fade[1]));
  if (o <= 0) return null;
  return <AbsoluteFill style={{ background: "#000", opacity: o }} />;
}
