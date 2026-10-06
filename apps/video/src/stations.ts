// The five stations, straight from the product catalogue.
import { STATIONS, stationById } from "../../web/lib/stations";

export { STATIONS, stationById };
export const STATION_FREQS = STATIONS.map((s) => s.freq);

export function nearestStation(f: number) {
  let best = STATIONS[0];
  let dist = Infinity;
  for (const s of STATIONS) {
    const d = Math.abs(s.freq - f);
    if (d < dist) {
      dist = d;
      best = s;
    }
  }
  return { station: best, dist };
}
