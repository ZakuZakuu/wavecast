import type { CSSProperties } from "react";

import { buildCover, type CoverBox, type CoverParams } from "../../lib/cover/build-cover";

const SANS = "var(--font-ui)";
const SERIF = "var(--font-serif)";

const cq = (value: number | null) => (value === null ? "auto" : `${value}cqw`);

function place(box: CoverBox): CSSProperties {
  return { position: "absolute", left: cq(box.left), right: cq(box.right), top: cq(box.top), bottom: cq(box.bottom), width: box.width === null ? undefined : cq(box.width) };
}

/**
 * Renders the cover v2 (Cover2.dc.html). Callers pass `bare` for anything
 * under 64px (mini player, library rows, blurred player background).
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
  const { title, stationLine, number } = cover;

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

      {number ? (
        <span style={{ ...place(number), fontFamily: "var(--font-numeric)", fontSize: "34cqw", fontWeight: 200, lineHeight: 1, letterSpacing: "-0.05em", color: number.color }}>
          {cover.freq}
        </span>
      ) : null}

      {cover.bare ? null : (
        <>
          <span
            style={{
              ...place(title),
              fontFamily: title.serif ? SERIF : "inherit",
              fontSize: cq(title.size),
              fontWeight: title.weight,
              lineHeight: title.lh,
              letterSpacing: title.ls,
              textAlign: title.align,
              writingMode: title.vertical ? "vertical-rl" : undefined,
              whiteSpace: "pre-line",
              color: title.color,
            }}
          >
            {cover.heading}
          </span>
          <span style={{ ...place(stationLine), fontSize: "4.6cqw", lineHeight: 1.3, textAlign: stationLine.align, whiteSpace: "nowrap", color: stationLine.color, opacity: 0.78 }}>
            {stationLine.freqText ? <span style={{ fontWeight: 300 }}>{stationLine.freqText}{cover.freq} </span> : null}
            <span style={{ fontWeight: 500 }}>{cover.station}</span>
          </span>
        </>
      )}
    </div>
  );
}
