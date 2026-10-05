// Renders stills at the given times (seconds) for frame-by-frame review:
//   pnpm still 0.5 3 6.2        -> out/stills/t0050.png ...
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { bundle } from "@remotion/bundler";
import { renderStill, selectComposition } from "@remotion/renderer";
import { FPS } from "../src/timeline";

async function main() {
  const times = process.argv.slice(2).map(Number).filter((n) => !Number.isNaN(n));
  const outDir = join(__dirname, "../out/stills");
  mkdirSync(outDir, { recursive: true });
  const serveUrl = await bundle({ entryPoint: join(__dirname, "../src/index.ts") });
  const browserExecutable = process.env.REMOTION_BROWSER_EXECUTABLE ?? null;
  const composition = await selectComposition({ serveUrl, id: "WaveCast", browserExecutable, chromiumOptions: { enableMultiProcessOnLinux: true } });
  for (const t of times) {
    const frame = Math.min(composition.durationInFrames - 1, Math.round(t * FPS));
    const output = join(outDir, `t${String(Math.round(t * 100)).padStart(5, "0")}.png`);
    await renderStill({ serveUrl, composition, frame, output, browserExecutable, chromiumOptions: { enableMultiProcessOnLinux: true }, imageFormat: "png", scale: Number(process.env.STILL_SCALE) || 0.5 });
    console.log(output);
  }
}
main().catch((e) => {
  console.error(e);
  process.exit(1);
});
