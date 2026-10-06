// Builds the film's sound offline, deterministically (fixed seeds):
//   public/sfx.wav    sound effects, peak ≈ -18 dBFS
//   public/music.wav  original score
//   public/mix.wav    music + effects, integrated loudness ≈ -16 LUFS, peak ≤ -1 dBFS
// All three run from 0 s for the whole film. scripts/render.ts cuts them to a range.
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { DURATION } from "../src/timeline";
import { lufs, Stereo, wav } from "./audio/dsp";
import { buildMusic } from "./audio/music";
import { buildSfx } from "./audio/sfx";

const dB = (x: number) => 20 * Math.log10(x);
const t0 = Date.now();

const sfx = buildSfx();
sfx.scale(Math.pow(10, -18 / 20) / sfx.peak());

const music = buildMusic();
// Music is set ~3 dB under its natural level so the effects read as accents above it;
// the stems keep this balance and the mix only adds overall gain.
music.scale(Math.pow(10, (-21 - lufs(music)) / 20));

const mix = new Stereo(DURATION);
mix.addStereo(0, music);
mix.addStereo(0, sfx);
mix.scale(Math.pow(10, (-16 - lufs(mix)) / 20));
// Soft knee above -3 dBFS keeps true peaks under -1 dBFS without audible clipping.
const ceiling = Math.pow(10, -1 / 20);
const knee = Math.pow(10, -3 / 20);
const soft = (x: number) => {
  const a = Math.abs(x);
  if (a <= knee) return x;
  return Math.sign(x) * (knee + (ceiling - knee) * Math.tanh((a - knee) / (ceiling - knee)));
};
for (let i = 0; i < mix.length; i++) {
  mix.L[i] = soft(mix.L[i]);
  mix.R[i] = soft(mix.R[i]);
}

const pub = join(__dirname, "../public");
mkdirSync(pub, { recursive: true });
writeFileSync(join(pub, "sfx.wav"), wav(sfx, 0, DURATION));
writeFileSync(join(pub, "music.wav"), wav(music, 0, DURATION));
writeFileSync(join(pub, "mix.wav"), wav(mix, 0, DURATION));
console.log(
  `audio (${((Date.now() - t0) / 1000).toFixed(1)}s): sfx peak ${dB(sfx.peak()).toFixed(1)} dBFS; ` +
    `music ${lufs(music).toFixed(1)} LUFS; mix ${lufs(mix).toFixed(1)} LUFS, peak ${dB(mix.peak()).toFixed(1)} dBFS`,
);
