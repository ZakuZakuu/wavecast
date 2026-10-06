import { Composition } from "remotion";
import { Film } from "./Film";
import { DURATION, FPS, HEIGHT, WIDTH } from "./timeline";
import "./fonts";

/** 1280×720 preview: the same 1920×1080 stage, scaled by 2/3. */
function Preview() {
  return (
    // Positioned, so the film's full-frame layers fill this 1920×1080 stage
    // (not the 720p canvas) before the whole stage is scaled once.
    <div style={{ position: "absolute", left: 0, top: 0, width: WIDTH, height: HEIGHT, overflow: "hidden", transform: `scale(${1280 / WIDTH})`, transformOrigin: "0 0" }}>
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
