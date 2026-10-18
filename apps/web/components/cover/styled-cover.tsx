import type { CSSProperties } from "react";

import { cssToStyle } from "../../lib/cover/styled/css";
import type { CoverView, TextBox } from "../../lib/cover/styled/types";

const absolute: CSSProperties = { position: "absolute", left: 0, top: 0, width: "100%", height: "100%" };

function Text({ box }: { box: TextBox }) {
  return box.text ? <span style={{ position: "absolute", ...cssToStyle(box.css) }}>{box.text}</span> : null;
}

/**
 * Draws a styled cover (lib/cover/styled): its layers (each a clipping box around an svg path), the grain, and
 * the title and caption words. `bare` leaves out the grain, which cannot be seen at the small sizes it is used for.
 */
export function StyledCover({ view, bare = false, radius = 12, className, style }: { view: CoverView; bare?: boolean; radius?: number; className?: string; style?: CSSProperties }) {
  return (
    <div
      className={className}
      aria-hidden="true"
      style={{
        width: "100%",
        aspectRatio: "1 / 1",
        position: "relative",
        overflow: "hidden",
        containerType: "inline-size",
        background: view.rootBg,
        borderRadius: radius,
        fontFamily: "var(--font-ui)",
        ...style,
      }}
    >
      {view.layers.map((layer, index) => (
        <div key={index} style={{ ...absolute, ...cssToStyle(layer.css) }}>
          <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice" style={{ width: "100%", height: "100%", display: "block", overflow: "visible", ...cssToStyle(layer.t) }}>
            <path d={layer.d} fill={layer.fill} stroke={layer.stroke} strokeWidth={layer.sw} strokeLinecap="round" strokeLinejoin="round" fillRule="evenodd" />
          </svg>
        </div>
      ))}
      {bare ? null : (
        <svg style={{ ...absolute, mixBlendMode: view.grain.blend as CSSProperties["mixBlendMode"], opacity: view.grain.opacity, pointerEvents: "none" }}>
          <filter id="wc-cover-grain" x="0" y="0" width="100%" height="100%">
            <feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="2" stitchTiles="stitch" />
            <feColorMatrix type="saturate" values="0" />
          </filter>
          <rect width="100%" height="100%" filter="url(#wc-cover-grain)" />
        </svg>
      )}
      <Text box={view.title} />
      <Text box={view.caption} />
      <Text box={view.caption2} />
    </div>
  );
}
