import type { CSSProperties } from "react";
import { buildCover, type CoverBox } from "../../../web/lib/cover/build-cover";
import type { StationId } from "../../../web/lib/stations";
import { SANS, SERIF } from "../fonts";
import { clamp, eo } from "../lib/math";

const cq = (value: number | null) => (value === null ? "auto" : `${value}cqw`);
function place(box: CoverBox): CSSProperties {
  return { position: "absolute", left: cq(box.left), right: cq(box.right), top: cq(box.top), bottom: cq(box.bottom), width: box.width === null ? undefined : cq(box.width) };
}

/**
 * The product's cover v2 (apps/web/lib/cover/build-cover.ts, rendered like
 * apps/web/components/cover/type-cover.tsx). `build` (0..1) grows it layer by
 * layer: background, each shape, the numeral, then the title.
 */
export function Cover({
  station,
  seed,
  heading,
  bare = false,
  build = 1,
  radius = 12,
  style,
}: {
  station: StationId;
  seed: number;
  heading: string;
  bare?: boolean;
  build?: number;
  radius?: number;
  style?: CSSProperties;
}) {
  const cover = buildCover({ stationId: station, seed, heading, bare });
  const { title, stationLine, number } = cover;
  const layers = cover.slots.length + 2;
  const layer = (i: number) => {
    const l = clamp(build * (layers + 0.6) - i);
    return { opacity: l, transform: `scale(${(0.9 + 0.1 * eo(l)).toFixed(4)})` };
  };
  const bgIn = clamp(build * 4);

  return (
    <div
      style={{
        width: "100%",
        aspectRatio: "1 / 1",
        position: "relative",
        overflow: "hidden",
        containerType: "inline-size",
        background: build >= 1 ? cover.bg : "transparent",
        borderRadius: radius,
        fontFamily: SANS,
        ...style,
      }}
    >
      {build < 1 ? <div style={{ position: "absolute", inset: 0, background: cover.bg, opacity: bgIn }} /> : null}
      <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice" style={{ position: "absolute", inset: 0, width: "100%", height: "100%", display: "block", overflow: "visible" }}>
        {cover.slots.map((slot, index) => {
          const ly = build >= 1 ? null : layer(index);
          return (
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
              style={ly ? { ...ly, transformBox: "fill-box", transformOrigin: "center" } : undefined}
            />
          );
        })}
      </svg>
      {number ? (
        <span style={{ ...place(number), fontSize: "34cqw", fontWeight: 200, lineHeight: 1, letterSpacing: "-0.05em", color: number.color, ...(build >= 1 ? null : layer(cover.slots.length)) }}>
          {cover.freq}
        </span>
      ) : null}
      {cover.bare ? null : (
        <div style={{ position: "absolute", inset: 0, ...(build >= 1 ? null : { ...layer(cover.slots.length + 1), transformOrigin: "30% 30%" }) }}>
          <span
            style={{
              ...place(title),
              fontFamily: title.serif ? SERIF : SANS,
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
        </div>
      )}
    </div>
  );
}
