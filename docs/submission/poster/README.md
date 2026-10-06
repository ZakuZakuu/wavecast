# 初赛海报（程序化）

三版 2400×3600 PNG（1200×1800 CSS px @2x），HTML/SVG 绘制，封面直接调用产品的封面生成器（`apps/web/lib/cover`）。

- `src/poster-a.html` 深色编辑风：一句话 → 节目时间线（音乐/主持同轨，播放头与生成前沿）→ 下一档推荐
- `src/poster-b.html` 暖色纸感：手机播放页 + 编号标注 + 右上调频旋钮
- `src/poster-c.html` 深夜靛蓝：环形调频盘，外圈刻度，中圈为放射状节目波形，圆心为那句话

```sh
./fetch-fonts.sh                       # Noto Sans/Serif SC（gitignored）
npm i esbuild playwright-core qrcode-generator   # 任意目录，下面用 NODE_PATH 指过去
NODE_PATH=<node_modules> node build.cjs          # dist/wc.js
NODE_PATH=<node_modules> node render.cjs [a b c] # out/*.png
```

节目标题、曲目、主持词为示意，不是真实生成结果。
