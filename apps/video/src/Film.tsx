import { AbsoluteFill, Audio, staticFile, useCurrentFrame } from "remotion";
import { FPS } from "./timeline";
import { Backdrop } from "./scenes/Backdrop";
import { ColdOpen } from "./scenes/ColdOpen";
import { Phone } from "./scenes/Phone";
import { Breakdown } from "./scenes/Breakdown";
import { HostSubtitles, Mixer } from "./scenes/NightOverlay";
import { EndCard, Wall } from "./scenes/Wall";
import { TextLayer } from "./scenes/Text";
import { Disclaimer, FadeOut, Grain, Vignette } from "./scenes/Overlays";

export function Film() {
  const t = useCurrentFrame() / FPS;
  return (
    <AbsoluteFill style={{ background: "#000", overflow: "hidden" }}>
      <Backdrop t={t} />
      <ColdOpen t={t} />
      <Wall t={t} />
      <Phone t={t} />
      <EndCard t={t} />
      <Breakdown t={t} />
      <Mixer t={t} />
      <TextLayer t={t} />
      <HostSubtitles t={t} />
      <Vignette t={t} />
      <Grain t={t} />
      <Disclaimer t={t} />
      <FadeOut t={t} />
      {/* Sound for Studio previews (renders are muted; scripts/render.ts muxes the mix). Built by scripts/build-audio.ts. */}
      <Audio src={staticFile("mix.wav")} />
    </AbsoluteFill>
  );
}
