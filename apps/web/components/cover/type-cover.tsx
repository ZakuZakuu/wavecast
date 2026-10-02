import type { CSSProperties } from "react";

import { buildCover, type CoverParams } from "../../lib/cover/build-cover";

const SANS = "var(--font-ui)";
const SERIF = "var(--font-serif)";

/**
 * Renders the TypeCover. Callers pass `bare` for anything under 64px (mini
 * player, library rows, blurred player background).
 */
export function TypeCover({
  params,
  radius = 12,
  className,
  style,
}: {
  params: CoverParams;
  radius?: number;
  className?: string;
  style?: CSSProperties;
}) {
  const cover = buildCover(params);
  const cq = (value: number) => `${value}cqw`;
  const show = !cover.bare;

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
        background: cover.bg,
        borderRadius: radius,
        fontFamily: SANS,
        ...style,
      }}
    >
      <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice" style={{ position: "absolute", inset: 0, width: "100%", height: "100%", display: "block" }}>
        {cover.slots.map((slot, index) => (
          <path
            key={index}
            d={slot.d}
            fill={slot.fill}
            fillOpacity={slot.o}
            stroke={slot.stroke}
            strokeWidth={slot.sw}
            strokeOpacity={slot.so}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ))}
      </svg>

      {show && cover.template === "freq" ? (
        <>
          <span style={{ position: "absolute", left: cq(3), bottom: cq(-6), fontFamily: "var(--font-numeric)", fontSize: cq(34), fontWeight: 200, lineHeight: 1, letterSpacing: "-0.05em", color: cover.p1 }}>{cover.freq}</span>
          <span style={{ position: "absolute", left: cq(7), top: cq(7), right: cq(7), display: "flex", flexDirection: "column", gap: cq(2) }}>
            <span style={{ fontSize: cq(cover.titleSize), fontWeight: 700, lineHeight: 1.15, letterSpacing: "-0.01em", whiteSpace: "pre-line", color: cover.onBg }}>{cover.heading}</span>
            <span style={{ fontSize: cq(5), fontWeight: 500, color: cover.onBg, opacity: 0.75 }}>{cover.station}</span>
          </span>
        </>
      ) : null}

      {show && cover.template === "label" ? (
        <>
          <span style={{ position: "absolute", left: cq(21), top: cq(21), width: cq(58), height: cq(58), display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: cq(1.6), textAlign: "center" }}>
            <span style={{ fontFamily: SERIF, fontSize: cq(cover.titleSize), fontWeight: 900, lineHeight: 1.2, whiteSpace: "pre-line", color: cover.onP2 }}>{cover.heading}</span>
            <span style={{ fontSize: cq(4), fontWeight: 500, letterSpacing: "0.08em", color: cover.onP2, opacity: 0.72 }}>{cover.station}</span>
          </span>
          <span style={{ position: "absolute", right: cq(5), bottom: cq(4), fontSize: cq(4.4), fontWeight: 300, color: cover.onBg, opacity: 0.75 }}>FM {cover.freq}</span>
        </>
      ) : null}

      {show && cover.template === "horizon" ? (
        <>
          <span style={{ position: "absolute", left: cq(7), bottom: cq(38), width: cq(60), fontSize: cq(cover.titleSize), fontWeight: 700, lineHeight: 1.15, whiteSpace: "pre-line", color: cover.onBg }}>{cover.heading}</span>
          <span style={{ position: "absolute", left: cq(7), top: cq(69), display: "flex", gap: cq(2.4), fontSize: cq(4.8), color: cover.onBg, opacity: 0.72 }}>
            <span style={{ fontWeight: 300 }}>FM {cover.freq}</span>
            <span style={{ fontWeight: 500 }}>{cover.station}</span>
          </span>
        </>
      ) : null}

      {show && cover.template === "column" ? (
        <>
          <span style={{ position: "absolute", left: 0, top: 0, width: cq(40), height: cq(80), display: "flex", justifyContent: "center", paddingTop: cq(8), boxSizing: "border-box" }}>
            <span style={{ writingMode: "vertical-rl", fontFamily: SERIF, fontSize: cq(cover.titleSize), fontWeight: 900, lineHeight: 1.25, letterSpacing: "0.08em", whiteSpace: "pre-line", color: cover.onP2 }}>{cover.heading}</span>
          </span>
          <span style={{ position: "absolute", left: 0, bottom: cq(6), width: cq(40), display: "flex", flexDirection: "column", alignItems: "center", gap: cq(0.8), color: cover.onP2 }}>
            <span style={{ fontSize: cq(4.6), fontWeight: 500, opacity: 0.8 }}>{cover.station}</span>
            <span style={{ fontFamily: "var(--font-numeric)", fontSize: cq(5.4), fontWeight: 200 }}>{cover.freq}</span>
          </span>
        </>
      ) : null}

      {show && cover.template === "contour" ? (
        <span style={{ position: "absolute", left: cq(7), top: cq(7), width: cq(64), display: "flex", flexDirection: "column", gap: cq(2) }}>
          <span style={{ fontSize: cq(cover.titleSize), fontWeight: 700, lineHeight: 1.15, whiteSpace: "pre-line", color: cover.onBg }}>{cover.heading}</span>
          <span style={{ display: "flex", gap: cq(2.4), fontSize: cq(4.8), color: cover.onBg, opacity: 0.72 }}>
            <span style={{ fontWeight: 300 }}>FM {cover.freq}</span>
            <span style={{ fontWeight: 500 }}>{cover.station}</span>
          </span>
        </span>
      ) : null}

      {show && cover.template === "split" ? (
        <>
          <span style={{ position: "absolute", left: cq(7), right: cq(7), bottom: cq(cover.splitBottom), fontSize: cq(cover.titleSize), fontWeight: 700, lineHeight: 1.12, letterSpacing: "-0.01em", whiteSpace: "pre-line", color: cover.onP1 }}>{cover.heading}</span>
          <span style={{ position: "absolute", left: cq(7), top: cq(cover.splitTop), display: "flex", gap: cq(2.4), fontSize: cq(4.8), color: cover.onBg, opacity: 0.75 }}>
            <span style={{ fontWeight: 300 }}>FM {cover.freq}</span>
            <span style={{ fontWeight: 500 }}>{cover.station}</span>
          </span>
        </>
      ) : null}
    </div>
  );
}
