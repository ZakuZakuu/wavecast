# 下一轮 UI：只读调研与讨论记录

2026-10-18（北京时间）。用户计划次日与 Claude 讨论和实现。**本轮只调研、记 issue，没有修改应用代码、没有修复 PR，也没有启动新的付费节目。** 文案保留与否、按钮位置、封面视觉方向均未替用户决定。

## 发布与收尾

- 正式发布 PR：[#318](https://github.com/ZakuZakuu/wavecast/pull/318)，main / integration 为 `485ea1252c070d090b57cf6bc3e1cc7814ca3d2f`。应用代码与已试听 `e85241c` 相同。
- 正式 API：`a96c34f9-82be-469d-93bf-c6ea2b37bffe` SUCCESS。正式 Web 继续使用原 READY 构建；已确认 Web 构建输入无变化。
- 复查 https://wavecast.space ：health、公开节目读取、未知节目/短码404、节目页面 OG 标题、未知短链均通过。部署后所查时间窗口没有 WARNING/ERROR/Traceback；这不是全量真机或新节目验收。
- #318 发布 CI 全绿，后端1741通过/3跳过，Web299通过；main 自动复跑 [39056788684](https://github.com/ZakuZakuu/wavecast/actions/runs/39056788684) 也已观测全部成功（同为后端1741通过/3跳过，Web299通过，Docker通过）。
- 保留后续问题：[#317](https://github.com/ZakuZakuu/wavecast/issues/317) 和弦/乐理符号口语化；[#319](https://github.com/ZakuZakuu/wavecast/issues/319) 心跳失活后生成恢复。用户明确本轮不修。

## 可行性概览

| 想法 | 已有基础 | 尚需补齐 |
| --- | --- | --- |
| 播放页展示歌曲封面 | 网易云歌曲详情确有专辑封面数据 | sidecar 至节目/前端的可选字段传递、加载失败兜底及展示设计 |
| 播放页一键生成整期 | 已有菜单操作、前端状态与 materialize 接口 | 复用同一操作，设计快捷入口及请求中/生成中/完成/失败状态 |
| 调频页后台生成整期 | 已有提案→创建 episode→FULL 持久化任务 | 不自动播放的入口、离页后的任务列表/结果归属和完成状态 |
| 生成完成提醒 | 可以读取 episode 状态；当前没有通知系统 | 站内提示较轻；关页/锁屏推送需要另接 Web Push，不是加按钮即可 |
| 上下首保留曲前口播、路线展示口播 | episode 已有旁白，MixPlan 已有 VOICE 实际时间 | 统一导航入口定义及路线条目；只使用已发布可播内容 |
| 辅助小字整理、封面多方案 | 已定位文案与确定性封面生成器 | 文案取舍与视觉方案由用户和 Claude 讨论 |

## 1. 网易云歌曲封面

已读取单独的 `ZakuZakuu/wavecast-music-dev` 仓库，查阅版本 `8a27b1f0710d6392eff0d10da82811f1ae810c51`：

- `netease_sidecar/upstream.py` 的歌曲详情调用 `/song/detail`；网易云数据中的 `al.picUrl` / `album.picUrl` 提供专辑封面。
- 做了一次无凭证、只读元数据验证：网易云歌曲 `1403218259`（丸ノ内サディスティック），详情返回 code=200、`album.picUrl` 非空，图片域名 `p1.music.126.net`。没有下载图片或请求音频。
- 查阅的 sidecar `NormalizedTrack` 只有专辑名称等字段，`normalize_track()` 没有透传封面。主仓库 `SidecarMusicProvider`、`ResolvedTrack`、`MusicSegment` 及前端类型也没有完整的封面数据通路。**上游有能力，不代表当前播放器已经拿到 URL。** 实施时应再核对线上 sidecar 的实际修订；本轮未把所查源码版本当作部署证明。
- 最小接法是随现有歌曲详情增加可选的专辑封面字段并传到播放数据，复用元数据缓存；不需要模型调用，不必为了封面引入新的研究阶段。旧节目无字段、空封面、图片不可达时应正常回退。
- 当前大图是节目封面，mini player、列表、分享图也依赖节目封面身份。歌曲封面放哪里、主持讲话时显示什么、是否切换两类封面，留给视觉讨论，不在这里决定。

主要位置：`backend/wavecast/providers/music_http.py`、`backend/wavecast/providers/contracts.py`、`backend/wavecast/intelligence/models.py`、`backend/wavecast/models/episode.py`、`apps/web/lib/types.ts`、`apps/web/components/player/player-screen.tsx`，以及单独的 music-dev 仓库。

## 2. 完整节目快捷入口与后台生成

### 播放页：已有能力可以复用

`MoreSheet` 当前调用 `prepareAndSaveEpisode()`，文案为“准备完整节目并保存”；它调用 `POST /api/episodes/{id}/materialize`，处理 requesting/preparing/完成/失败，并在完成后保存节目。快捷入口可直接复用该动作，不应另写一条生成管线；是否同时保存、按钮放哪里，仍需确认。

主要位置：`apps/web/components/player/more-sheet.tsx`、`apps/web/lib/use-programme-playback.ts`、`apps/web/components/player/player-screen.tsx`。

### 调频页：后端已有 FULL，前端需要独立的启动方式

现在 `useTuneStart()` 在拿到 proposal 后调用全局播放器 `open()`，首段音频就绪后自动进入播放页；直接复用整套 hook 会自动开播，不满足“只后台生成”。可复用提案及已有 `api.start()` / `api.materialize()`，将 UI 意图与自动播放分开，沿用服务端持久化 FULL 任务，不用浏览器定时器维持整期生成。

仍有几处需要产品与实现一起定义：

- 请求成功后才提示“已开始后台生成”，已有任务重复点击不重复创建节目；不会替换当前正在听的另一档节目。
- 后台任务需有可重新进入的入口，包含 queued/generating/ready/failed 的实际状态；当前没有现成的面向 UI 的生成任务列表 API。
- 现有“保存完成节目”的前端动作依赖页面收到完成状态。登录用户的 saved API 也只接受 MATERIALIZED；不能把“页面关闭后服务器自动保存并提醒”视为已实现。需要补齐结果归属/列表，游客与登录用户分别考虑。
- MATERIALIZED、HLS 全部渲染完、MP3 导出完成是不同状态。提醒“生成好了”具体表示哪一层，需要先约定，避免把调用 materialize 成功当作生成完成。
- 既有 [#204](https://github.com/ZakuZakuu/wavecast/issues/204) 已记录调频后台生成，本次应更新该 issue，而非再建相同需求。排查 #319 时也需覆盖在途渐进任务升级 FULL 的情形，但本轮不修。

主要位置：`apps/web/components/tune/use-tune-start.ts`、`apps/web/components/tune/tune-page.tsx`、`apps/web/lib/api.ts`、`apps/web/lib/user-library.ts`、`services/api/main.py`、`backend/wavecast/storage/generation_jobs.py`。

### 提醒可分开评估

- 站内：前台通过现有 episode 状态/SSE 更新提示或节目库状态，属于较小扩展；重进页面后也应能读回状态，不能只依赖一次 toast。
- 关页/锁屏：当前仓库有 manifest，但没找到 Service Worker、PushManager、通知订阅或服务端推送实现。需要订阅存储、完成事件发送及用户授权。iPhone 普通 Safari 标签页不能直接等同主屏幕 Web App 的推送能力；WebKit 文档要求加入主屏幕后，由用户直接操作触发授权。
- 是否做提醒、先做到哪一档，由用户和 Claude 决定；不能承诺普通标签页关闭后仍可仅靠前端轮询提醒，也不需要为调研接入外部通知服务。

资料：[Apple Web Push](https://developer.apple.com/documentation/usernotifications/sending-web-push-notifications-in-web-apps-and-browsers)、[WebKit iOS/iPadOS Web Push](https://webkit.org/blog/13878/)、[MDN Notifications](https://developer.mozilla.org/en-US/docs/Web/API/Notifications_API/Using_the_Notifications_API)。

## 3. 上下首与节目路线包含口播

已确认现状：

- `nextProgramMusicStart()` / `previousProgramMusicStart()` 只看 MixPlan 的 MUSIC lane。上一首还保留“已播放超过3秒则重播当前歌曲”的惯例。
- `routeChapters()` 虽将同章/独立桥段归组，但最终 rows 只筛 MUSIC，点击也用歌曲自己的 start；这解释了用户反馈。
- MixPlan 已提供 VOICE 的实际起点，episode 已提供旁白状态/角色；`publishedNarration()` 也已能过滤已发布的旁白，不必新增模型或重新编排音频。

可行的精简方向：在同一前端导航视图中，为歌曲计算“本首的默认收听入口”——有已发布、可播的前置口播时从那段开始，否则用歌曲起点；上下首、路线点击及系统 nexttrack 共用该定义。路线增加可辨识的旁白条目和时间，而非将长主持词全文塞进列表。

实施前需明确/覆盖：正在听曲前口播时再点下一首不能反复回到同一入口；上一首3秒重播语义以哪里计时；首段台呼、开篇、独立双人桥段、末尾收束、音乐中穿插的旁白不能仅靠“最近一段 VOICE”粗略归属；未发布或 SKIPPED/草稿不能成为跳转点。已有 `musicChaptersForEpisode()` 可复用，但仍需验证跨章桥段与实际混音关系。

主要位置：`apps/web/lib/playback.ts`、`apps/web/lib/now-playing.ts`、`apps/web/components/player/player-screen.tsx`、`apps/web/components/player/route-sheet.tsx`、`apps/web/lib/use-programme-playback.ts`、`apps/web/components/programme-audio-player.tsx`。

## 4. 辅助文案：只列现状，不决定删除

见[逐项清单](ui-microcopy-inventory-2026-10-18.md)。包括两处用户点名的常驻小字、空态、操作反馈、调频等待、详情/分享、节目库及账户/浏览器提示。列出原文、出现条件、代码位置；不替用户决定保留、删除、改写或只显示一次。

## 5. 节目封面：下一轮与 Claude 设计几版

当前不是图片生成模型，而是确定性 SVG/排版封面：`build-cover.ts` 提供 column/label/freq/horizon/contour/split 六种模板，每台从三个候选中按种子选择，并变化配色和构图。节目 ID/来源卡片别名保证同档封面稳定。

可以扩展模板与构图，或先做多版静态设计评审，再接进现有 renderer；不必先引入图片生成服务。本轮没有替用户选择风格或制作新稿。后续设计应一起查看播放页大图、首页、节目库、mini player、分享/OG 和 MediaSession artwork；留意长中外文标题、无字小图、深浅背景，以及同一节目跨页面一致性。歌曲封面与节目封面是两条相关但不同的设计任务。

主要位置：`apps/web/lib/cover/build-cover.ts`、`apps/web/lib/cover/programme-cover.ts`、`apps/web/components/cover/type-cover.tsx`、`apps/web/lib/stations.ts`。已有视觉资料在 `docs/design/frost/TypeCover.dc.html`、`TypeCovers.dc.html` 和 `HANDOFF.md`；代码注释所提 `Cover2.dc.html` 当前未找到，不当作已存在文件交接。

## 本轮边界与明日讨论

先确认视觉和交互范围，再让 Claude 实施。建议把“播放页快捷整期生成”和“调频后台生成+通知”看成可分别交付的范围；这只是工作量判断，不替代用户决策。文案去留和封面方案保持待讨论。本轮没有新增修复 PR、修改服务变量、通知其他人或启动新节目。

## 已整理的 issue

- [#320 播放页歌曲/专辑封面](https://github.com/ZakuZakuu/wavecast/issues/320)
- [#204 播放页快捷整期生成、调频后台生成与可选提醒](https://github.com/ZakuZakuu/wavecast/issues/204)（更新既有需求，未重复建单）
- [#321 导航优先曲前口播与路线展示旁白](https://github.com/ZakuZakuu/wavecast/issues/321)
- [#322 辅助小字盘点，去留待用户决定](https://github.com/ZakuZakuu/wavecast/issues/322)
- [#323 节目封面多版视觉设计](https://github.com/ZakuZakuu/wavecast/issues/323)
