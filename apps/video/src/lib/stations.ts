import { STATIONS, type StationId } from "../../../web/lib/stations";
import { content } from "../content";

// Name, frequency, colour and cover hue come from the web app's station
// catalogue. The cover templates and dark odds below are the sample film's
// (cover v1), which the approved covers were drawn with.
const FILM_COVER: Record<StationId, { tpl: string[]; dark: number }> = {
  casual: { tpl: ["freq", "split"], dark: 0.25 },
  crate: { tpl: ["label", "split"], dark: 0.45 },
  portrait: { tpl: ["label", "split"], dark: 0.35 },
  lineage: { tpl: ["contour", "freq"], dark: 0.4 },
  night: { tpl: ["horizon", "contour"], dark: 0.85 },
};

export type FilmStation = {
  id: StationId;
  n: string;
  f: number;
  fs: string;
  c: string;
  d: string;
  hue: number;
  tpl: string[];
  dark: number;
};

export const STA: FilmStation[] = STATIONS.map((s) => ({
  id: s.id,
  n: s.name,
  f: s.freq,
  fs: s.freq.toFixed(1),
  c: s.light,
  d: content.stations[s.id],
  hue: s.cover.hue,
  ...FILM_COVER[s.id],
}));

export const station = (id: StationId) => STA.find((s) => s.id === id)!;
