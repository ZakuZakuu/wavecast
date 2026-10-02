// Renders the PWA / home-screen icons from lib/brand/logo-mark.ts.
// Usage (from apps/web): node --experimental-strip-types scripts/render-icons.mjs
// Requires Playwright with a Chromium build (pre-installed in dev containers).
import { writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import process from "node:process";

import { logoMarkSvg } from "../lib/brand/logo-mark.ts";

const require = createRequire(import.meta.url);
let playwright;
try {
  playwright = require("playwright");
} catch {
  playwright = require(process.env.PLAYWRIGHT_MODULE ?? "playwright");
}

const outputs = [
  { file: "public/icons/icon-192.png", size: 192, svg: logoMarkSvg() },
  { file: "public/icons/icon-512.png", size: 512, svg: logoMarkSvg() },
  { file: "public/icons/maskable-192.png", size: 192, svg: logoMarkSvg({ square: true, contentScale: 0.8 }) },
  { file: "public/icons/maskable-512.png", size: 512, svg: logoMarkSvg({ square: true, contentScale: 0.8 }) },
  { file: "public/apple-touch-icon.png", size: 180, svg: logoMarkSvg({ square: true }) },
];

writeFileSync("app/icon.svg", logoMarkSvg() + "\n");

const browser = await playwright.chromium.launch();
const page = await browser.newPage();
for (const output of outputs) {
  await page.setViewportSize({ width: output.size, height: output.size });
  await page.setContent(
    `<html><body style="margin:0;background:transparent">${output.svg.replace("<svg ", `<svg width="${output.size}" height="${output.size}" `)}</body></html>`,
  );
  await page.locator("svg").screenshot({ path: output.file, omitBackground: true });
}
await browser.close();
