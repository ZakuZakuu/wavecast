// node build.cjs  →  dist/wc.js   (needs esbuild + qrcode-generator resolvable, e.g. via NODE_PATH)
const esbuild = require("esbuild");
esbuild.buildSync({ entryPoints: ["src/wc.ts"], bundle: true, format: "iife", outfile: "dist/wc.js", target: "es2020", logLevel: "info", nodePaths: (process.env.NODE_PATH || "").split(":").filter(Boolean) });
