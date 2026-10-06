import { BRAND } from "../content";
import { TILES, tileAppearAt } from "./wallLayout";
import { Cover } from "../components/Cover";
import { SANS } from "../fonts";
import { ei, eio, eo, lerp, p } from "../lib/math";
import { logoMarkSvg } from "../../../web/lib/brand/logo-mark";
import { END, NEXT } from "../timeline";
import { textIn } from "./Text";

const SIZE = 172;

export const WALL_COUNT = TILES.length;

export function Wall({ t }: { t: number }) {
  const [w0] = NEXT.wall;
  if (t < w0 || t > END.gather[1] + 0.2) return null;
  const [g0, g1] = END.gather;
  return (
    <div style={{ position: "absolute", inset: 0 }}>
      {TILES.map((tile, i) => {
        // Waves from the centre outwards.
        const at = tileAppearAt(tile);
        const appear = eo(p(t, at, at + 0.6));
        if (appear < 0.002) return null;
        const build = p(t, at, at + 1.3);
        // Gather: fly to the centre and shrink, outer ones a beat later.
        const gs = g0 + (tile.d / 5) * 0.5;
        const g = eio(p(t, gs, gs + (g1 - g0) * 0.7));
        const x = lerp(tile.x, 960, g);
        const y = lerp(tile.y, 520, g);
        const s = lerp(0.86 + 0.14 * appear, 0.12, g);
        const op = appear * (1 - ei(p(t, gs + (g1 - g0) * 0.45, gs + (g1 - g0) * 0.7)));
        if (op < 0.002) return null;
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: x - SIZE / 2,
              top: y - SIZE / 2,
              width: SIZE,
              height: SIZE,
              opacity: op,
              transform: `scale(${s.toFixed(4)})`,
              borderRadius: 14,
              overflow: "hidden",
              boxShadow: "0 12px 30px rgba(29,29,31,.14)",
            }}
          >
            <Cover station={tile.station} seed={tile.seed} heading={tile.heading} build={build} radius={0} />
          </div>
        );
      })}
    </div>
  );
}

export function EndCard({ t }: { t: number }) {
  if (t < END.icon - 0.1) return null;
  const icon = eo(p(t, END.icon, END.icon + 0.9));
  const svg = logoMarkSvg().replace("<svg ", '<svg width="150" height="150" ');
  return (
    <div style={{ position: "absolute", left: 0, right: 0, top: 300, display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center", fontFamily: SANS, color: "#1D1D1F" }}>
      <div
        style={{ width: 150, height: 150, opacity: icon, transform: `scale(${lerp(0.4, 1, icon).toFixed(4)})`, filter: `drop-shadow(0 18px 30px rgba(29,29,31,${(0.18 * icon).toFixed(3)}))` }}
        dangerouslySetInnerHTML={{ __html: svg }}
      />
      <div style={{ marginTop: 34, fontSize: 96, fontWeight: 600, letterSpacing: "-0.03em", lineHeight: 1.15, ...strip(textIn(t, END.name, null)) }}>{BRAND.name}</div>
      <div style={{ marginTop: 14, fontSize: 40, fontWeight: 500, color: "#86868B", ...strip(textIn(t, END.line, null)) }}>{BRAND.endLine}</div>
      <div style={{ marginTop: 44, fontSize: 28, fontWeight: 500, ...strip(textIn(t, END.url, null)) }}>{BRAND.url}</div>
    </div>
  );
}
const strip = <T extends { op: number }>({ op: _op, ...rest }: T) => rest;
