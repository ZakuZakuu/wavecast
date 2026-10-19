# WaveCast Project State

Updated: 2026-10-19（北京时间）。唯一当前状态入口。旧过程记录已归档，不能把其中“未发布／待试听”等描述当成当前事实。

## 当前任务

Claude 正在推进界面与完整版后台生成；Codex 独立处理英文口号 TTS 发音。用户已授权小修通过检查后合入 integration 测试，不发布 main。核心仅改 `spoken_form.py` 与 `dialogue_pipeline.py`：完整 music/life 口号的朗读大小写消歧、双人纯中英文也经过既有发音转换、Writer 使用自然英文大小写。展示稿、事实引用、真正缩写、已发布音频保持原样；不新增模型调用、复审、数据库迁移或前端改动。详见[发音与短测记录](design/tts-pronunciation-checks.md)。

本地相关回归285通过，Ruff/Mypy通过；完整回归交CI。当前环境未注入豆包播客密钥，提供三种大小写的显式短测脚本，真实读音仍待新节目试听。和弦符号读法仍留在[#317](https://github.com/ZakuZakuu/wavecast/issues/317)，本次不扩大；心跳失活后恢复问题见[#319](https://github.com/ZakuZakuu/wavecast/issues/319)，不重构租约。

已发布的开篇/收尾、正文讨论交付、中文口播名与节目方向传递见[ADR 0032](adr/0032-editorial-opening.md)至[0035](adr/0035-substantive-opening-and-closing.md)。用户此前已接受听感后发布#318，旧节目不补稿。开场方法论见[原设计](design/programme-editorial-method-and-opening.md)，台标音乐留后续。之前的[UI只读调研](design/ui-next-round-research-2026-10-18.md)与[辅助文案盘点](design/ui-microcopy-inventory-2026-10-18.md)仅供背景，当前UI实现以本节下方和最新代码为准。

## 界面优化第二轮（仅前端为主，在integration测试环境）

首页推荐在前（特色卡+横滑），电台瓦片在后，下拉刷新（#324/#326）；封面库9风格×20图案×5构图（`apps/web/lib/cover/styled`，#323），分享预览图与锁屏封面同步（#328）；上下首含口播（#321）；新手引导（#325，`lib/guide`）：清单驱动，新功能只需在`registry.ts`加一条并给元素加`data-guide`，账户页可重看。收藏红心与节目库左滑收藏/删除/撤销（#330）；“我调的”不再依赖服务器逐个回答。

**完整版（#204，见[ADR 0036](adr/0036-full-version-in-background.md)）**：整档节目在后台准备，播放页标题行/更多菜单和调频页“准备完整版”进入，节目库行显示准备中/已准备好/准备失败（重试），完成后顶部横幅+节目库红点。每个听众同时最多2档，20分钟未完成算失败；游客可用。新增后端接口 `POST/GET /api/full-versions`、`materialize` 加限制；前端 `lib/full-versions.ts`。**已发布节目（#331，见[ADR 0037](adr/0037-published-programmes.md)）**：分享的是做好的节目本身。分享面板（播放页、详情页）先问要不要准备完整版→整期一次混完（界面只说一般1–2分钟，不编百分比）→校验→链接可用；别人打开链接得到自己的一份副本（进度、收藏各自，不生成、不占额度），共用同一份固定音频；撤回/删除不影响已有副本；节目库那一行只有一个标记（分享中=分享图标，听过的完整版=打钩圆圈）。新增表 `published_programmes`、`programme_listens`（迁移0009，**部署前需跑迁移**）；旧的“每个访客重新生成”链接返回410“已失效”。容量：每人最多10档、同时2个混音、已发布音频预算默认卷的一半（`WAVECAST_PUBLISHED_AUDIO_BUDGET_MB`）、给生成永远留150 MB；**真实节目发布测试前测试卷要先扩容，正式发布前扩生产卷**。下架开关 `WAVECAST_TAKEN_DOWN_PROGRAMMES`。**大家都在听（#327，见[ADR 0038](adr/0038-public-shelf.md)）**：首页“猜你想听”下面的横滑板块，内容是别人选了“所有人”的已发布节目；近7天被听次数+时间衰减+新鲜度，每个作者最多10档，一批6档，缓存3分钟，换一批按已显示id翻页，不足3档整块不显示；`GET /api/public-shelf`；已发布节目封面一律由自己的id生成，分享链接不再带`?c=`。**播放页歌曲封面（#320）**：网易云专辑封面经 sidecar 的 `cover_url`（[wavecast-music-dev#11](https://github.com/ZakuZakuu/wavecast-music-dev/pull/11)，**sidecar 需重新部署，新节目才带封面**）一路带到 `MusicSegment.cover_url`（可选，旧节目没有）；播放页用“叠放”：两张同样大的封面错开26px，点一下前后互换；开播前节目封面在前，开播后歌曲封面在前，旁白时保持上一首的封面；手动选过就按选的（本次访问内记住）；图片没加载成功或没有封面就只显示节目封面。前端 `lib/song-cover.ts`、`components/player/player-cover.tsx`。#322/深色模式待定。

## 已发布基线

- 正式站 **https://wavecast.space**。#318 `485ea12` 已发布，后端1741通过/3跳过、Web299通过、Docker通过；main后来合入界面#329，当前分支头`467687b`。不要将旧的“#318待发布”记录当作现状。
- 正式API仍观测为`a96c34f9-82be-469d-93bf-c6ea2b37bffe` SUCCESS，固定源码`485ea12`；main分支前进不代表固定SHA的API自动更新。正式Web构建与API分别核对，不强求两端SHA一致。
- integration已包含Claude的UI二轮与完整版后台任务；TTS修复基于`bcd4e2b`独立开发，合并时保留后续并行提交。测试环境更新可能打断正在生成的任务，完成检查点需观察实际部署成功及健康信号。

- 当前链路：Pro 研究规划／素材、Lite 写稿，豆包单人 TTS 与双人播客，Exa 检索。单人取消常规模型核对、改写和逐句删减；完整前文、来源、日期／人物状态约束和必要代码检查保留。见 [ADR 0031](adr/0031-one-pass-radio-writing.md)。
- 已发布播放器恢复、主持词窗口、旁白时长取整、响度和旧清单兼容、写稿防重复、按节目用量持久化。旧稿和已发布音频不重写；没有新增数据库迁移。上一轮用户确认播放无硬性阻塞，接受文笔剩余问题后发布。

## 部署与排查要点

- Railway 项目 `45d78b7e-2d61-4dc0-b9eb-5788eb1bff84`，环境 `26f5b192-0523-44d8-a1fa-2ee1b8d2eae1` 名为 production，但正式与测试是独立服务／数据库。
- 正式 API 服务 `c6a6389b-634e-4c32-b5dd-34cd5407e1fe`，https://wavecast.up.railway.app ，当前固定在已验收发布 SHA。
- 测试 API 服务 `ac7a2c75-e66f-477e-aeb3-71d029ccc337`，https://integration-test-api-production.up.railway.app ，跟随 integration；测试网页 https://wavecast-web-git-integration-zaku-zakuu.vercel.app 。合并 integration 可能打断测试生成任务。
- 用户授权将测试 API 的 `WAVECAST_GUEST_PROGRAM_LIMIT` 从5调至50（同一访客累计创建额度），已重部署成功并通过只读API冒烟。正式服务与全站日额度未改；OAuth只读回变量名，写入工具已确认设置。
- Vercel 项目 `prj_WGzuADDs2X85j2KJpfobAvjoOW23`，team `team_lSnGo6eYVVyDSW7rGC1BYyyx`。本次受控发布曾临时关闭自动域名分配；用户随后明确同意，**已恢复 autoAssignCustomDomains=true**。不要沿用“仍待授权恢复”的旧记录。
- 生产的 Ark／播客／普通 TTS 三项密钥通过 Railway 变量引用复用 integration-test-api 的密钥；删除测试服务或改动密钥前先迁移引用。模型 ID 与行为选择器是生产明确值。生产数据库、认证、音乐拓扑和卷保留原配置。
- 生产旧代码未必能读取新节目状态，回退优先向前修复或独立回退 Web，不假定直接重部署旧 API 一定安全。Web 后端地址与预览保护也要按具体部署核实。
- `GET /api/episodes/{id}/usage` 有归属检查，用量按节目持久化、币种分开、未知费用单列。已有节目听回不等于重新生成，不主动为检查启动额外付费验收。
- 历史测试样本 `ba9829b5-62b8-44e4-b1fb-c7cd8f1fcc59`（方大同的情歌慢热，#309 版）约 27 分钟；新写稿测试样本 `e916617c-715f-4b6d-8512-f33647fdb821`（#310 版）。这些仅供历史对照。

## 长期边界与资料入口

- 音乐连续性优先，已播放／已可跳转前缀保持不可变，未来未发布内容可调整。离开播放页继续播放是已实现行为；不等于退出收听会话。
- 程序生成已有角色分工；本轮不做大规模播放器／运行时重构。电台默认表达已有部分配置，不代表完整的五台编辑方法已经实现。
- 调试先按具体节目、稿件、素材和日志建立证据。历史的曲目背景结构化偶发失败、手机后台租约恢复原因不明等，不凭推测扩大修复。
- [AGENTS](../AGENTS.md)、[产品目标](PRELIMINARY_PRODUCT_TARGET.md)、[长期产品与架构合同](CODEX_HANDOFF.md)、[Frost 设计](design/frost/HANDOFF.md)、[部署 runbook](deployment/railway-vercel.md)、[CI](deployment/ci.md)。
- 本次收敛前的完整状态保存在 [历史归档](history/PROJECT_STATE-before-opening-2026-10-16.md)，更早记录也保持；归档不是当前任务清单。
