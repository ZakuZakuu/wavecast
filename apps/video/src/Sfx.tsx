// Places the offline-synthesised sound effects (public/sfx, built by
// scripts/synth-sfx.mjs) on the timeline at the sample's EV times.
import { Audio, Sequence, staticFile, useVideoConfig } from "remotion";
import { EV } from "./timeline";

/** Master level for every effect. Kept low: the programme audio goes on top in the edit. */
export const SFX_VOLUME = 0.6;

export function Sfx() {
  const { fps } = useVideoConfig();
  return (
    <>
      {EV.map((e, i) => (
        <Sequence key={i} from={Math.round(e.t * fps)} layout="none" name={`sfx ${e.k}`}>
          <Audio src={staticFile(`sfx/${e.k}.wav`)} volume={SFX_VOLUME} />
        </Sequence>
      ))}
    </>
  );
}
