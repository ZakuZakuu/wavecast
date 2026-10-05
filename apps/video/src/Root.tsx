import { Composition } from "remotion";
import { Film } from "./Film";
import { DURATION, FPS, HEIGHT, WIDTH } from "./timeline";
import "./fonts";

export function Root() {
  return <Composition id="WaveCast" component={Film} durationInFrames={DURATION * FPS} fps={FPS} width={WIDTH} height={HEIGHT} />;
}
