import { Composition } from "remotion";
import { Film } from "./Film";
import { DURATION, FPS, HEIGHT, WIDTH } from "./timeline";
import "./fonts";

/** 1280×720 preview: the same 1920×1080 stage, scaled by 2/3. */
function Preview() {
  return (
    <div style={{ width: WIDTH, height: HEIGHT, transform: "scale(0.6666667)", transformOrigin: "0 0" }}>
      <Film />
    </div>
  );
}

export function Root() {
  return (
    <>
      <Composition id="WaveCast" component={Film} durationInFrames={DURATION * FPS} fps={FPS} width={WIDTH} height={HEIGHT} />
      <Composition id="WaveCastPreview" component={Preview} durationInFrames={DURATION * FPS} fps={FPS} width={1280} height={720} />
    </>
  );
}
