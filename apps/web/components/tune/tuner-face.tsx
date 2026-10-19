import { memo, useId, type CSSProperties } from "react";

import { rgba } from "../../lib/cover/styled/color";
import { formatFreq, STATIONS, type Station } from "../../lib/stations";
import { cardNoise, noisePath, posterPose, stationBlends, tintBlend } from "../../lib/tuner";
import { StationPoster } from "./station-poster";

const DUST = noisePath(120, 120, 70, 31);

const gradient = (station: Station) => `linear-gradient(120deg, ${station.tint}, ${station.tint2})`;

/** Name, frequency and one-liner of a station, faded by how near the dial is to it. */
const StationWords = memo(function StationWords({ station, weight }: { station: Station; weight: number }) {
  return (
    <div
      className="face-words"
      style={{ opacity: weight, visibility: weight <= 0 ? "hidden" : undefined, "--deep": station.deep, "--deep-text": station.deepText } as CSSProperties}
      aria-hidden={weight < 0.5 ? true : undefined}
    >
      <span className="face-pill">FM {formatFreq(station.freq)}</span>
      <span className="face-name">{station.name}</span>
      <p className="face-tagline">{station.tagline}</p>
    </div>
  );
});

/**
 * What the tuner card shows at a frequency: the tint of the nearest station with its neighbour laid over, each
 * station's words faded by its distance, static over it all between two stations, and the pictures of the two
 * nearest stations, flown out to the right (and up) as the dial leaves them and back in as it arrives.
 * A function of the frequency alone, so dragging back plays it in reverse and a stopped finger stops it.
 */
export function TunerFace({ freq }: { freq: number }) {
  // Two faces can be on screen at once (the page's and the guide's): each needs its own pattern id.
  const dustId = `tuner-dust-${useId().replace(/[^a-zA-Z0-9]/g, "")}`;
  const blends = stationBlends(freq);
  const tint = tintBlend(freq);
  const nearest = blends.reduce((best, item) => (item.distance < best.distance ? item : best), blends[0]);
  return (
    <>
      <span className="face-tint" style={{ background: gradient(tint.base) }} aria-hidden="true" />
      <span className="face-tint" style={{ background: gradient(tint.over), opacity: tint.amount }} aria-hidden="true" />
      <span className="face-gloss" aria-hidden="true" />
      <svg className="face-dust" style={{ opacity: cardNoise(nearest.distance) }} aria-hidden="true">
        <defs>
          <pattern id={dustId} width="120" height="120" patternUnits="userSpaceOnUse">
            <path d={DUST} />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill={`url(#${dustId})`} />
      </svg>
      {blends.map((item) => (item.weight > 0 ? <StationWords key={item.station.id} station={item.station} weight={item.weight} /> : null))}
      {STATIONS.map((station, index) => {
        const item = blends[index];
        if (item.away >= 1) return null;
        const pose = posterPose(item.away);
        return (
          <div
            key={station.id}
            className="face-poster"
            style={{
              transform: `translate3d(${pose.x}px, ${pose.y}px, 0) rotate(${pose.rotate}deg) scale(${pose.scale})`,
              background: station.tint,
              boxShadow: `0 30px 34px -12px ${rgba(station.deep, 0.5)}, 0 12px 20px rgba(29, 29, 31, .14), 0 2px 4px rgba(29, 29, 31, .1)`,
            }}
            aria-hidden="true"
          >
            <StationPoster stationId={station.id} />
          </div>
        );
      })}
    </>
  );
}
