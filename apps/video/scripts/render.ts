// Renders the film: one silent H.264 video, the sound-effect bed as a separate
// WAV aligned to the video's first frame, and the music cue sheet.
//
//   pnpm render [--quality preview|final] [--range <segment>|<from>-<to>]
//
// quality: preview = 1280×720 (default), final = 1920×1080.
// range:   cold, morning, afternoon, night, nextday, ending, or seconds such as
//          "12-30" / "47.3-58.2". Empty renders the whole film.
import { execFileSync } from "node:child_process";
import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
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

const quality = arg("quality") || "preview";
if (quality !== "preview" && quality !== "final") throw new Error(`quality must be preview or final, got "${quality}"`);
const rangeArg = arg("range");

let from = 0;
let to = DURATION;
if (rangeArg) {
  const seg = SEGMENTS[rangeArg.toLowerCase()];
  const m = /^(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)$/.exec(rangeArg);
  if (seg) [from, to] = seg;
  else if (m) [from, to] = [Number(m[1]), Number(m[2])];
  else throw new Error(`range must be one of ${Object.keys(SEGMENTS).join(", ")} or "<from>-<to>" seconds, got "${rangeArg}"`);
  if (!(from >= 0 && to <= DURATION && to > from)) throw new Error(`range ${from}-${to} is outside 0-${DURATION}`);
}
const f0 = Math.round(from * FPS);
const f1 = Math.round(to * FPS) - 1;
const frames = f1 - f0 + 1;

const run = (cmd: string, args: string[]) => execFileSync(cmd, args, { cwd: ROOT, stdio: "inherit" });
const t0 = Date.now();
mkdirSync(OUT, { recursive: true });

run("npx", ["tsx", "scripts/build-charset.ts"]);
run("npx", ["tsx", "scripts/build-sfx.ts"]);
run("npx", ["tsx", "scripts/build-cues.ts"]);

// Sound effects: cut the full bed to exactly the rendered frames, so the WAV
// starts at the video's 0 s and has the same length.
{
  const wav = readFileSync(join(ROOT, "public/sfx.wav"));
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
  writeFileSync(join(OUT, "wavecast-sfx.wav"), Buffer.concat([header, data]));
}

// Benchmarked: two or more parallel tabs are ~1.5× faster than one, with no
// gain past two on 4 cores. Remotion's default (half the cores) gives a single
// tab on a 2-core runner, so use every core.
const cores = availableParallelism();
const concurrency = Number(process.env.REMOTION_CONCURRENCY) || cores;
const composition = quality === "final" ? "WaveCast" : "WaveCastPreview";
const output = join(OUT, "wavecast-film-silent.mp4");
console.log(`render: ${composition} (${quality}), frames ${f0}-${f1} (${from}s-${to}s, ${frames} frames), concurrency ${concurrency}/${cores} cores`);
const t1 = Date.now();
run("npx", ["remotion", "render", "src/index.ts", composition, output, "--muted", `--frames=${f0}-${f1}`, `--concurrency=${concurrency}`]);
const done = Date.now();
console.log(`timing: setup ${((t1 - t0) / 1000).toFixed(0)}s, video ${((done - t1) / 1000).toFixed(0)}s (${((done - t1) / frames).toFixed(0)} ms/frame)`);
writeFileSync(
  join(OUT, "render-info.txt"),
  `quality=${quality}\nrange=${rangeArg || "full"} (${from}s-${to}s)\nframes=${frames}\ncores=${cores}\nconcurrency=${concurrency}\nvideo_seconds=${((done - t1) / 1000).toFixed(0)}\n`,
);
copyFileSync(join(ROOT, "music-cues.md"), join(OUT, "music-cues.md"));
