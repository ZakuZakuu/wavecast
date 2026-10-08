# WaveCast 演示短片（Remotion）

`docs/design/film/wavecast-film.html` 样稿的正式版本：1920×1080，30 fps，76 秒。每一帧只由 `t = frame / fps` 决定，没有 `Math.random`，重复渲染结果一致。

| 文件 | 内容 |
| --- | --- |
| `src/content.ts` | **所有文字内容**：字幕、节目标题、歌名、主持词、节目路线、推荐卡片、封面种子。换成真实节目时只改这个文件。 |
| `src/timeline.ts` | 时间点、相机（`KEYS`）、手指（`FINGER`）、调谐曲线（`tuneF`）、字幕时间、音效事件表（`EV`）。 |
| `src/Film.tsx` | 画面，样稿 `render(t)` 的移植。 |
| `src/lib/cover.ts` | 样稿的封面生成器 `makeCover`。 |
| `scripts/synth-sfx.mjs` | 按样稿参数离线合成音效 WAV（输出到 `public/sfx/`，不提交）。 |
| `markers.md` | 建议放入真实节目音频的时间位置。 |

复用 `apps/web`：App 图标（`lib/brand/logo-mark.ts`）、电台名称 / 频率 / 颜色 / 封面色相（`lib/stations.ts`）。

## 本地预览

```sh
pnpm install
pnpm --dir apps/video studio       # 先合成音效，再打开 Remotion Studio
```

## 本地渲染

```sh
pnpm --dir apps/video render         # out/wavecast-demo.mp4（带音效）
pnpm --dir apps/video render:silent  # out/wavecast-demo-silent.mp4（无声）
pnpm --dir apps/video still out/frame.png --frame=1170   # 单帧
```

字体通过 `@remotion/google-fonts` 从 Google Fonts 加载（Noto Sans SC / Noto Serif SC），渲染时需要能访问 fonts.gstatic.com。

## CI 渲染

GitHub → Actions → **Demo film** → Run workflow。完成后在该次运行页面底部下载 `wavecast-demo-film`（两个 MP4 和 markers.md）。

## 许可

Remotion 不是 MIT 许可：个人、3 人以内的公司和非营利组织可以免费使用（含商用），更大规模的公司需要购买 Company License。见 `node_modules/remotion/LICENSE.md`。
