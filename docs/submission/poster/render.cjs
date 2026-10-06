// node render.cjs [name...]  →  out/<name>.png at 2400×3600 (1200×1800 @2x)
const { chromium } = require("playwright-core");
const path = require("path");
const names = process.argv.slice(2).length ? process.argv.slice(2) : ["v1", "v2"];
(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROME || "/opt/pw-browsers/chromium-1194/chrome-linux/chrome", args: ["--no-sandbox"] });
  for (const n of names) {
    const page = await browser.newPage({ viewport: { width: 1200, height: 1800 }, deviceScaleFactor: 2 });
    page.on("pageerror", (e) => console.error(n, "pageerror", e.message));
    await page.goto("file://" + path.resolve(`src/poster-${n}.html`));
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(400);
    await page.screenshot({ path: `out/${n}.png` });
    console.log("rendered", n);
    await page.close();
  }
  await browser.close();
})();
