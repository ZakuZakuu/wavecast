// Checks that the 720p preview composition shows exactly the final 1080p
// picture, only smaller: one still per segment from each composition, the
// final one downscaled to 1280×720, then compared pixel by pixel.
// Fails when the mean difference, or any 1/6-height band's, exceeds the limit
// (a mis-scaled stage leaves whole bands empty or shifted).
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { bundle } from "@remotion/bundler";
import { renderStill, selectComposition } from "@remotion/renderer";
import { FPS } from "../src/timeline";

const POINTS: Array<[string, number]> = [
  ["cold", 4],
  ["morning", 14],
  ["afternoon", 52],
  ["night", 75],
  ["nextday", 106],
  ["ending", 122],
];
const MEAN_LIMIT = 4; // out of 255; grain and resampling alone stay near 1
const BAND_LIMIT = 8;

async function main() {
  const sharp = await import("sharp").then((m) => m.default);
  const out = join(__dirname, "../out/check-preview");
  mkdirSync(out, { recursive: true });
  const serveUrl = await bundle({ entryPoint: join(__dirname, "../src/index.ts") });
  const browserExecutable = process.env.REMOTION_BROWSER_EXECUTABLE ?? null;
  const final = await selectComposition({ serveUrl, id: "WaveCast", browserExecutable });
  const preview = await selectComposition({ serveUrl, id: "WaveCastPreview", browserExecutable });
  let failed = false;
  for (const [name, t] of POINTS) {
    const frame = Math.round(t * FPS);
    const fp = join(out, `${name}-final.png`);
    const pp = join(out, `${name}-preview.png`);
    await renderStill({ serveUrl, composition: final, frame, output: fp, browserExecutable, imageFormat: "png" });
    await renderStill({ serveUrl, composition: preview, frame, output: pp, browserExecutable, imageFormat: "png" });
    const a = await sharp(fp).resize(1280, 720, { kernel: "lanczos3" }).removeAlpha().raw().toBuffer();
    const b = await sharp(pp).removeAlpha().raw().toBuffer();
    if (a.length !== b.length) throw new Error(`${name}: size mismatch`);
    const bands = Array(6).fill(0);
    let sum = 0;
    const row = 1280 * 3;
    for (let i = 0; i < a.length; i++) {
      const d = Math.abs(a[i] - b[i]);
      sum += d;
      bands[Math.min(5, Math.floor(i / row / 120))] += d;
    }
    const mean = sum / a.length;
    const worstBand = Math.max(...bands.map((s) => s / (row * 120)));
    const ok = mean <= MEAN_LIMIT && worstBand <= BAND_LIMIT;
    if (!ok) failed = true;
    console.log(`${ok ? "ok  " : "FAIL"} ${name.padEnd(9)} t=${t}s  mean ${mean.toFixed(2)}  worst band ${worstBand.toFixed(2)}`);
  }
  if (failed) {
    console.error(`preview does not match final (limits: mean ${MEAN_LIMIT}, band ${BAND_LIMIT}); stills in out/check-preview`);
    process.exit(1);
  }
}
main().catch((e) => {
  console.error(e);
  process.exit(1);
});
