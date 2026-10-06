# 初赛海报（程序化）

2400×3600 PNG（1200×1800 CSS px @2x），HTML/SVG 绘制，封面直接调用产品的封面生成器（`apps/web/lib/cover`），底色与光效取自视频早晨场景，墨色与毛玻璃取自前端 Frost tokens。

- `src/poster-v1.html` 封面错落堆叠，大封面做主角，主持词与歌单做页边批注
- `src/poster-v2.html` 超大标题，封面做成横穿画面的一条带子
- `src/seeds.html` 封面 seed 色板，用来挑柔和的 seed

题目、歌单、主持词、“因为你常听…”均为示意，不是真实生成结果。

```sh
./fetch-fonts.sh                                  # Noto Sans/Serif SC（gitignored）
npm i esbuild playwright-core qrcode-generator    # 任意目录，下面用 NODE_PATH 指过去
NODE_PATH=<node_modules> node build.cjs           # dist/wc.js
NODE_PATH=<node_modules> node render.cjs [v1 v2]  # out/*.png
```
