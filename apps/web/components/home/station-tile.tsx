import Link from "next/link";

import { formatFreq, type Station, type StationId } from "../../lib/stations";

// One line icon per station on a 24px grid, in two tones: "s" stroke only, "f" solid, "sf" stroke plus
// a soft fill (fo = fill strength). The same icon, enlarged and cropped, is the tile's quiet texture.
type Part = { d: string; k: "s" | "f" | "sf"; fo?: number };
const circle = (cx: number, cy: number, r: number) => `M${cx - r} ${cy}a${r} ${r} 0 1 0 ${2 * r} 0a${r} ${r} 0 1 0 ${-2 * r} 0Z`;

const ICONS: Record<StationId, { parts: Part[]; ghost: string }> = {
  // radio dial: a half-disc gauge with a needle
  casual: {
    parts: [{ d: "M4 16a8 8 0 0 1 16 0Z", k: "sf", fo: 0.4 }, { d: "M12 16l3.6-5.2", k: "s" }, { d: "M3.5 19.5h17", k: "s" }, { d: circle(12, 16, 1.3), k: "f" }],
    ghost: "translate(38 -20) scale(4)",
  },
  // record: tinted disc, label, groove highlight
  crate: {
    parts: [{ d: circle(12, 12, 9), k: "sf", fo: 0.3 }, { d: circle(12, 12, 3.2), k: "sf", fo: 0.95 }, { d: "M12 5.2a6.8 6.8 0 0 1 6.8 6.8", k: "s" }, { d: circle(12, 12, 0.9), k: "f" }],
    ghost: "translate(40 -2) scale(4)",
  },
  // microphone with a tinted capsule
  portrait: {
    parts: [{ d: "M12 3a3 3 0 0 0-3 3v5.5a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3Z", k: "sf", fo: 0.55 }, { d: "M6 11.5a6 6 0 0 0 12 0", k: "s" }, { d: "M12 17.5V21", k: "s" }, { d: "M9 21h6", k: "s" }],
    ghost: "translate(42 -26) scale(4)",
  },
  // a line that branches, with filled nodes
  lineage: {
    parts: [{ d: "M6 7.5v9", k: "s" }, { d: "M6 14c0-2 1.5-2 4-2h6", k: "s" }, { d: circle(6, 5.5, 2), k: "sf", fo: 0.95 }, { d: circle(6, 18.5, 2) + circle(18, 12, 2), k: "sf", fo: 0.95 }],
    ghost: "translate(36 -20) scale(4)",
  },
  // crescent moon and a small sparkle
  night: {
    parts: [{ d: "M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z", k: "sf", fo: 0.5 }, { d: "M18 4v3M16.5 5.5h3", k: "s" }],
    ghost: "translate(38 -8) scale(4)",
  },
};

function Parts({ parts, ink, soft, fillScale }: { parts: Part[]; ink: string; soft: string; fillScale: number }) {
  return parts.map((part, index) => (
    <path
      key={index}
      d={part.d}
      style={{
        fill: part.k === "f" ? ink : part.k === "sf" ? soft : "none",
        fillOpacity: part.k === "f" ? 1 : (part.fo ?? 0) * fillScale,
        stroke: part.k === "f" ? "none" : ink,
      }}
    />
  ));
}

/** Home station shortcut: a pale tile in the station's colours, its icon, and the same icon as a faint texture. */
export function StationTile({ station }: { station: Station }) {
  const icon = ICONS[station.id];
  return (
    <Link
      href={`/tune?station=${station.id}`}
      className="station-tile"
      style={{ "--tile-light": station.light, "--tile-deep": station.deep } as React.CSSProperties}
      aria-label={`FM ${formatFreq(station.freq)} ${station.name}，${station.line}`}
    >
      <svg className="station-tile-ghost" viewBox="0 0 116 52" aria-hidden="true">
        <g transform={icon.ghost}><Parts parts={icon.parts} ink="var(--tile-light)" soft="var(--tile-light)" fillScale={0.6} /></g>
      </svg>
      <svg className="station-tile-icon" viewBox="0 0 24 24" aria-hidden="true">
        <Parts parts={icon.parts} ink="var(--tile-deep)" soft="var(--tile-light)" fillScale={1} />
      </svg>
      <span className="station-tile-copy">
        <span className="station-tile-name">{station.name}</span>
        <span className="station-tile-freq tabular">{formatFreq(station.freq)}</span>
      </span>
    </Link>
  );
}
