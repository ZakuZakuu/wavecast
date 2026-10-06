// Renders the film:
//   wavecast-film-silent.mp4   H.264 picture only
//   wavecast-sfx.wav           sound effects   ┐ each starts at the video's 0 s
//   wavecast-music.wav         score           │ and has the same length
//   wavecast-mix.wav           mix, ≈ -16 LUFS ┘
//   wavecast-film.mp4          the silent video with the mix muxed in (video stream copied)
//   music-cues.md, render-info.txt
//
//   pnpm render [--quality preview|final] [--range <segment>|<from>-<to>] [--audio-only]
//
// quality: preview = 1280×720 (default), final = 1920×1080.
// range:   cold, morning, afternoon, night, nextday, ending, or seconds such as
//          "12-30". Empty renders the whole film.
// --audio-only: rebuild the sound and re-mux it into the existing
//          out/wavecast-film-silent.mp4; the range comes from that video's
//          render-info.txt, so picture and sound always line up.
import { execFileSync } from "node:child_process";
import { copyFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { availableParallelism } from "node:os";
import { join } from "node:path";
import { DURATION, FPS, SEG } from "../src/timeline";

const ROOT = join(__dirname, "..");
const OUT = join(ROOT, "out");

const SEGMENTS: Record<string, readonly [number, number]> = {
  cold: SEG.cold,
  morning: SEG.morning,
  afternoon: SEG.afternoon,
  night: SEG.night,
  nextday: SEG.nextMorning,
  ending: SEG.end,
};

function arg(name: string): string {
  const i = process.argv.indexOf(`--${name}`);
  const v = i >= 0 ? process.argv[i + 1] : process.env[`FILM_${name.toUpperCase()}`];
  return (v ?? "").trim();
}
const audioOnly = process.argv.includes("--audio-only") || process.env.FILM_MODE === "audio";

function parseRange(r: string): [number, number] {
  if (!r || r === "full") return [0, DURATION];
  const seg = SEGMENTS[r.toLowerCase()];
  const m = /^(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)$/.exec(r);
  let out: [number, number];
  if (seg) out = [seg[0], seg[1]];
  else if (m) out = [Number(m[1]), Number(m[2])];
  else throw new Error(`range must be one of ${Object.keys(SEGMENTS).join(", ")} or "<from>-<to>" seconds, got "${r}"`);
  if (!(out[0] >= 0 && out[1] <= DURATION && out[1] > out[0])) throw new Error(`range ${out[0]}-${out[1]} is outside 0-${DURATION}`);
  return out;
}

const info = join(OUT, "render-info.txt");
let quality = arg("quality") || "preview";
let rangeArg = arg("range");
if (audioOnly) {
  if (!existsSync(join(OUT, "wavecast-film-silent.mp4")) || !existsSync(info)) {
    throw new Error("--audio-only needs out/wavecast-film-silent.mp4 and out/render-info.txt from an earlier video render");
  }
  const prev = Object.fromEntries(readFileSync(info, "utf8").split("\n").filter(Boolean).map((l) => l.split("=") as [string, string]));
  quality = prev.quality;
  rangeArg = (prev.range ?? "full").split(" ")[0];
}
if (quality !== "preview" && quality !== "final") throw new Error(`quality must be preview or final, got "${quality}"`);
const [from, to] = parseRange(rangeArg);
const f0 = Math.round(from * FPS);
const f1 = Math.round(to * FPS) - 1;
const frames = f1 - f0 + 1;

const run = (cmd: string, args: string[]) => execFileSync(cmd, args, { cwd: ROOT, stdio: "inherit" });
const t0 = Date.now();
mkdirSync(OUT, { recursive: true });

run("npx", ["tsx", "scripts/build-charset.ts"]);
run("npx", ["tsx", "scripts/build-audio.ts"]);
run("npx", ["tsx", "scripts/build-cues.ts"]);
const tAudio = Date.now();

/** Cut a full-length WAV to exactly the rendered frames. */
function cutWav(src: string, dst: string) {
  const wav = readFileSync(src);
  const dataStart = 44;
  const blockAlign = wav.readUInt16LE(32);
  const rate = wav.readUInt32LE(24);
  const s0 = Math.round((f0 / FPS) * rate);
  const n = Math.round((frames / FPS) * rate);
  const total = (wav.length - dataStart) / blockAlign;
  const data = Buffer.alloc(n * blockAlign);
  wav.copy(data, 0, dataStart + s0 * blockAlign, dataStart + Math.min(total, s0 + n) * blockAlign);
  const header = Buffer.from(wav.subarray(0, dataStart));
  header.writeUInt32LE(36 + data.length, 4);
  header.writeUInt32LE(data.length, 40);
  writeFileSync(dst, Buffer.concat([header, data]));
}
for (const name of ["sfx", "music", "mix"]) cutWav(join(ROOT, `public/${name}.wav`), join(OUT, `wavecast-${name}.wav`));

const cores = availableParallelism();
const concurrency = Number(process.env.REMOTION_CONCURRENCY) || cores;
let videoSeconds = 0;
if (!audioOnly) {
  // Benchmarked: two or more parallel tabs are ~1.5× faster than one, with no
  // gain past two on 4 cores. Remotion's default (half the cores) gives a single
  // tab on a 2-core runner, so use every core.
  const composition = quality === "final" ? "WaveCast" : "WaveCastPreview";
  console.log(`render: ${composition} (${quality}), frames ${f0}-${f1} (${from}s-${to}s, ${frames} frames), concurrency ${concurrency}/${cores} cores`);
  const tv = Date.now();
  run("npx", ["remotion", "render", "src/index.ts", composition, join(OUT, "wavecast-film-silent.mp4"), "--muted", `--frames=${f0}-${f1}`, `--concurrency=${concurrency}`]);
  videoSeconds = (Date.now() - tv) / 1000;
}

// Mux: copy the video stream, add the mix as AAC.
const ffmpeg = (() => {
  try {
    execFileSync("ffmpeg", ["-version"], { stdio: "ignore" });
    return ["ffmpeg"];
  } catch {
    return ["npx", "remotion", "ffmpeg"];
  }
})();
run(ffmpeg[0], [...ffmpeg.slice(1), "-y", "-v", "error", "-i", join(OUT, "wavecast-film-silent.mp4"), "-i", join(OUT, "wavecast-mix.wav"), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "256k", "-shortest", join(OUT, "wavecast-film.mp4")]);

const done = Date.now();
console.log(`timing: audio ${((tAudio - t0) / 1000).toFixed(0)}s, video ${audioOnly ? "skipped" : `${videoSeconds.toFixed(0)}s (${((videoSeconds * 1000) / frames).toFixed(0)} ms/frame)`}, total ${((done - t0) / 1000).toFixed(0)}s`);
if (!audioOnly) {
  writeFileSync(info, `quality=${quality}\nrange=${rangeArg || "full"} (${from}s-${to}s)\nframes=${frames}\ncores=${cores}\nconcurrency=${concurrency}\nvideo_seconds=${videoSeconds.toFixed(0)}\n`);
}
copyFileSync(join(ROOT, "music-cues.md"), join(OUT, "music-cues.md"));
