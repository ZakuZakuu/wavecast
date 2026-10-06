# 初赛海报（程序化）

2400×3600 PNG（1200×1800 CSS px @2x），HTML/SVG 绘制，封面直接调用产品的封面生成器（`apps/web/lib/cover`），底色与光效取自视频早晨场景，墨色与毛玻璃取自前端 Frost tokens。

- `src/poster-v1.html` 封面错落堆叠，大封面做主角，主持词与歌单做页边批注
- `src/poster-v2.html` 超大标题，封面做成横穿画面的一条带子
- `src/poster-v3.html` 在 V1 基础上：主角换成手机首页，两张封面从屏幕空位“飞出”，下半部为调谐窗口 + 输入框 + 开播按钮，网址为 www.wavecast.space
- `src/poster-v4.html` 以 App 图标里的小收音机为主角，画成暖白色的实物；封面从它上方弧形升起，电波圈层向外扩散；显示窗里是“说一句”的输入与指针
- `src/poster-v5.html` 三张真实页面（调频页、播放页、首页，按 `docs/design/frost/Frost-*.dc.html` 还原）串成“说一句，听一档，再来下一档”，无手机外壳，电台色光晕沿用视频
- `src/poster-v6.html` 在 V3 基础上重做：手机里是真实首页（封面全部到位，无空位），两张封面放大“弹出”并带淡淡的拖影，周围一圈封面墙；下方换成照前端设计还原的凹槽刻度窗，不再有输入框和橙色按钮
- `src/seeds.html` 封面 seed 色板，用来挑柔和的 seed

题目、歌单、主持词、“因为你常听…”均为示意，不是真实生成结果。

```sh
./fetch-fonts.sh                                  # Noto Sans/Serif SC（gitignored）
npm i esbuild playwright-core qrcode-generator    # 任意目录，下面用 NODE_PATH 指过去
NODE_PATH=<node_modules> node build.cjs           # dist/wc.js
NODE_PATH=<node_modules> node render.cjs [v1 v2]  # out/*.png
```
