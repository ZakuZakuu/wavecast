# WaveCast Project State

Updated: 2026-10-07. **唯一的当前状态入口**；记录现状、下一步和已知问题，不累积会话日志。

## 当前阶段与产品

Listening P0 和 UI P0 已完成用户验收；用户确认国内正式环境已上线。当前工作是腾讯音乐高校 AI Hackathon 初赛提交材料，尚未确认已提交。Demo：**https://wavecast.space**。

WaveCast 是 AI 音乐电台：用户说一句想听什么，围绕主题检索资料、选曲、规划路线和生成主持讲解；音乐与背景故事组成一档连续节目，边播边生成；收听兴趣再影响推荐，形成主动探索与音乐发现的闭环。默认体验以音乐为主、主持适量出现；不能把产品退回成歌单加逐曲 TTS。

**差异化（2026-10-07 收敛，详见 [目标文档 §0](PRELIMINARY_PRODUCT_TARGET.md)）：** 从用户想听的一个问题出发，把音乐与它背后的故事编成一档专属电台节目，减少搜索、理解和拼接零散内容的成本。长尾兴趣是展示价值的入口，也服务日常陪伴；不假设相关内容在别处完全不存在。音乐是真实歌曲，主持声音为合成。质量标准是讲解有依据、选曲扣题、听感自然、路线完整且有真实收尾；创意推荐的线上状态仍待核实。

用户曾验收一档约 20 分钟、4 首歌且有收尾的完整节目；这是一次成功验收，不是所有主题的时长保证，也不是最低歌曲数量要求。保留不可变已发布前缀、确定性生命周期、连续播放优先和有界 AI 成本。产品约束见 [PRELIMINARY_PRODUCT_TARGET.md](PRELIMINARY_PRODUCT_TARGET.md)。

## 现在做什么

1. **初赛海报 V7 已定稿（用户 2026-10-07 确认），随初赛材料一并提交。** 简介沿用原稿小幅调整，用户已定稿，仅提交时使用，不入仓库。海报的信息层级与最终文案见 [提交材料](submission/preliminary.md)；源码与导出方法在分支 `claude/kind-carson-sv2kei` 的 `docs/submission/poster/`（未合并，PNG 不入库）。旧的 B/B2 与 A/B/C 候选均已放弃。
2. 待用户决定：提交前是否保留易进入的首页选题，再加入一两个具体、有吸引力且真实试听通过的主题（只涉及 `apps/web/lib/featured.ts`，低风险）；线上 AI 推荐规划器：用户反馈生产已设为 DeepSeek，尚未由我们核实线上实际表现，对外只写“收听兴趣带来推荐”，不写“创意选题”。
3. 提交前浏览器引导已实现，待 integration 预览/真机验收：微信首次访问复用 Safari 安装卡样式，引导外部浏览器并支持复制当前链接、失败手动复制和继续体验；桌面补浏览器建议，二维码固定本站首页。仅前端改动，未发布 main；本地 203 tests、lint、typecheck、生产构建通过，截图为模拟 UA，不代表微信真机播放验收。
4. 提交前以材料和具体阻塞为主，避免无关功能发布；初赛后按确认的优先级处理已知问题，再评估电台风格后端接线、主持词和 TTS 精校。没有授权启动新的广泛运行时重构。

## 已交付与边界

- Frost 前端：调谐窗/拨轮、开播流程、播放器、NowLine、主持文稿、三层进度、节目路线、常驻迷你条、首页/节目库、偏好弹层、PWA 安装引导、账户/登录、动效、电脑及安卓适配。主要设计依据：[HANDOFF](design/frost/HANDOFF.md)、[MOTION](design/frost/MOTION.md)；实际实现以 `apps/web` 为准。
- 播放逻辑在 `apps/web/lib/use-programme-playback.ts`；常驻 host 在 `apps/web/components/player/playback-provider.tsx`。离开播放页继续播放是已实现行为；浏览页面不等于结束收听会话。
- 封面 v2 已在 `apps/web/lib/cover/build-cover.ts`；五台配置在 `apps/web/lib/stations.ts`，每台三个候选模板、按 seed 参数化。五台为随便听 88.7、唱片行 93.1、人物志 97.4、来龙去脉 101.5、夜里 105.8。
- 电台选择目前是前端配置/关键词匹配，不能声称后端已按五台分别编排。P1 方案见 Frost HANDOFF 第 9 节，尚待独立任务验证实施。
- 登录推荐是 programme proposals；游客“先听这几档”是固定选题入口，点击后真实生成，并非预制 mock 音频节目。不要把所有固定选题等同于 mock。
- 原始 `Cover2.dc.html`、`Frost-Login.dc.html`、`Frost-Account.dc.html` 不在当前 integration 的设计目录中；不应给新会话提供不存在的文件链接。封面和账户实现可直接查代码，若要严格复刻原稿再向设计方取得源文件。
- 纯 mock 音源带参数的渲染路径此前存在不能完整播放的问题；不能用注入假 manifest 的截图证明真实音频验收。

## 分支、部署与验证

2026-10-07 核对的 Git 状态（随下一次发布更新）：

| 分支/PR | 状态 |
| --- | --- |
| `main` | `bd0abad`，#168 release 合并提交 |
| `integration` | `09cc552`，#175–#177 文档更新已合并，包含 #169 Vercel ignore-build 修复；当前与 main 并非同一提交 |
| `feat/concept-film` / [#174](https://github.com/ZakuZakuu/wavecast/pull/174) | 独立宣传片 PR，未合并；head `3dc5145` |

正式 Web 由 Vercel 跟随 main，Railway API 为正式后端；用户已完成正式域名/OAuth/Railway 配置。此处 Git SHA 不等于重新核实的线上部署 SHA。部署运行规则及域名登录见 [runbook](deployment/railway-vercel.md)，CI 选择见 [ci.md](deployment/ci.md)。

开发：功能分支 → PR 到 integration → 合并后的托管预览验收 → release PR integration → main（普通 merge commit）→ integration 快进到 main 合并提交；不 force push。不为了获得预览把未验收工作推 main。integration/main 保留，保护长期分支，避免合并后自动删除 integration。

只有已知 Web/文档路径的 integration PR 自动跳过 backend 与 Docker smoke；Web 检查仍跑。main release 运行全量 CI。没有新 Claude 配置要求；不要通过 CI skip 指令节省额度。部署合并本身可能触发托管动作，应集中成完整验收点。

## 已知问题：事实与待查原因分开

2026-10-06 确认以下 issue 均 open：

| Issue | 现象与方向 |
| --- | --- |
| [#171](https://github.com/ZakuZakuu/wavecast/issues/171) | 缓冲充足仍显示“正在准备”。检查可播放余量及完成状态；45 秒是状态展示阈值，不是后端续生成策略阈值。保留主持展示优先级与完成收尾。 |
| [#172](https://github.com/ZakuZakuu/wavecast/issues/172) | 人物志预估 42 分钟，完成后约 18 分钟。需核对目标、可用曲目、路线/终止条件和音频前缀显示口径；尚未证明“路线没走完”是根因。 |
| [#173](https://github.com/ZakuZakuu/wavecast/issues/173) | 中文界面出现长日文节目标题；封面无字是既有长标题降级。待明确中文标题与独立封面短标题（不超过 8 汉字）的合同及兼容。 |

Claude 另报告泛化章节名“第 N 段”、偶发播放错误及提示遮挡封面；目前仅为待复现反馈，未在本次核实为已建 issue 或已确认根因。先取得节目 URL/ID 和日志，不泛化为所有节目故障。

## 文档与协作入口

- `AGENTS.md`：仓库规则、文档管理与职责分工。
- 本文件：当前快照，保持短；历史原文已完整保存到 [历史归档](history/PROJECT_STATE-through-2026-10-02.md)，归档不是当前任务清单。
- `CODEX_HANDOFF.md`：长期架构合同；开头 Narration P0、旧 Actions 额度故障等明确是历史，不作为当前限制。
- `docs/adr/`：已决架构；设计规范放 `docs/design/`，部署操作放 `docs/deployment/`，提交材料放 `docs/submission/`。
- **Codex 负责整体规划、事实核对和统一状态；Claude 按单项任务实施。**交接给 Claude 时只传目标、相关文件/资产、约束、验收和交付方式，不让其重复梳理全部历史。实现者汇报差异与验证，Codex 汇总进本文件；不新建另一个 CURRENT_STATUS 或把会话全文塞进快照。
