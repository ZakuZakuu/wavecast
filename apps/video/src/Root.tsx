import { Composition } from "remotion";
import { Film } from "./Film";
import { DURATION, FPS, HEIGHT, WIDTH } from "./timeline";

export function Root() {
  const common = { component: Film, durationInFrames: DURATION * FPS, fps: FPS, width: WIDTH, height: HEIGHT };
  return (
    <>
      <Composition id="WaveCastDemo" {...common} defaultProps={{ sfx: true }} />
      <Composition id="WaveCastDemoSilent" {...common} defaultProps={{ sfx: false }} />
    </>
  );
}
