// Which moment's light is on screen, as crossfade weights. Shared by the
// backdrop, vignette, disclaimer and anything that adapts light/dark.
import { COLD, NIGHT, AFTERNOON, SEG } from "./timeline";
import { eio, p } from "./lib/math";

export type Light = { black: number; morning: number; afternoon: number; night: number };

export function light(t: number): Light {
  const dawn = eio(p(t, COLD.dawn[0], COLD.dawn[1]));
  const toAfternoon = eio(p(t, AFTERNOON.light[0], AFTERNOON.light[1]));
  const toNight = eio(p(t, NIGHT.light[0], NIGHT.light[1]));
  const toMorning = eio(p(t, NIGHT.light2[0], NIGHT.light2[1]));
  const black = 1 - dawn;
  let morning = dawn * (1 - toAfternoon);
  const afternoon = toAfternoon * (1 - toNight);
  const night = toNight * (1 - toMorning);
  morning += toMorning;
  return { black, morning: morning * (1 - black), afternoon, night };
}

/** 0 = light scene, 1 = dark scene. */
export const darkness = (t: number) => {
  const l = light(t);
  return Math.min(1, l.black + l.night);
};

export const inSeg = (t: number, seg: keyof typeof SEG) => t >= SEG[seg][0] && t < SEG[seg][1];
