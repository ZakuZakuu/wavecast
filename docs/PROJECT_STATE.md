# WaveCast Project State

Updated: 2026-10-09（第 8 项）；其余 2026-10-08。**唯一的当前状态入口**；记录现状、下一步和已知问题，不累积会话日志。

## 当前阶段与产品

Listening P0 和 UI P0 已完成用户验收；用户确认国内正式环境已上线。当前工作是腾讯音乐高校 AI Hackathon 初赛提交材料，尚未确认已提交。Demo：**https://wavecast.space**。

WaveCast 是 AI 音乐电台：用户说一句想听什么，围绕主题检索资料、选曲、规划路线和生成主持讲解；音乐与背景故事组成一档连续节目，边播边生成；收听兴趣再影响推荐，形成主动探索与音乐发现的闭环。默认体验以音乐为主、主持适量出现；不能把产品退回成歌单加逐曲 TTS。

**差异化（2026-10-07 收敛，详见 [目标文档 §0](PRELIMINARY_PRODUCT_TARGET.md)）：** 从用户想听的一个问题出发，把音乐与它背后的故事编成一档专属电台节目，减少搜索、理解和拼接零散内容的成本。长尾兴趣是展示价值的入口，也服务日常陪伴；不假设相关内容在别处完全不存在。音乐是真实歌曲，主持声音为合成。质量标准是讲解有依据、选曲扣题、听感自然、路线完整且有真实收尾；创意推荐的线上状态仍待核实。

用户曾验收一档约 20 分钟、4 首歌且有收尾的完整节目；这是一次成功验收，不是所有主题的时长保证，也不是最低歌曲数量要求。保留不可变已发布前缀、确定性生命周期、连续播放优先和有界 AI 成本。产品约束见 [PRELIMINARY_PRODUCT_TARGET.md](PRELIMINARY_PRODUCT_TARGET.md)。

## 现在做什么

1. **初赛海报 V7 已定稿（用户 2026-10-07 确认），随初赛材料一并提交。** 简介沿用原稿小幅调整，用户已定稿，仅提交时使用，不入仓库。海报的信息层级与最终文案见 [提交材料](submission/preliminary.md)；源码与导出方法在分支 `claude/kind-carson-sv2kei` 的 `docs/submission/poster/`（未合并，PNG 不入库）。旧的 B/B2 与 A/B/C 候选均已放弃。
2. 待用户决定：提交前是否保留易进入的首页选题，再加入一两个具体、有吸引力且真实试听通过的主题（只涉及 `apps/web/lib/featured.ts`，低风险）；线上 AI 推荐规划器：用户反馈生产已设为 DeepSeek，尚未由我们核实线上实际表现，对外只写“收听兴趣带来推荐”，不写“创意选题”。
3. 浏览器引导 #178 已随 #180 发布到 main；微信外部浏览器引导、桌面建议和固定首页二维码已实现，本地 203 tests/lint/typecheck/build 通过，真机验收待用户完成。
4. 邮箱验证码登录已发布 main（#179/#180）：Resend 发信、同邮箱复用用户 ID、账户显示邮箱；Google 保持基础权限 Testing。2026-10-08 用户在正式环境确认新登录页显示正常、登录可用。绑定管理/改邮箱/账号合并后续再做；预览环境未配置登录，认证流程在 wavecast.space 验收。
5. 用户授权准备 Claude 独立云端节目精校环境，使用开发专用 key、本机 PG/音频与本地音乐 sidecar/upstream，不接正式数据库或 Railway 音乐服务。安装/启动/只读评审导出见 [cloud review](deployment/claude-cloud-review.md)。先 mock 验收再显式单档 live；当前仅完成本地无付费检查，云端启动/真实音源/付费生成待配置后验收。初赛正式环境保持稳定，不启动广泛运行时重构。
6. **已发布 main（#183，2026-10-08）：** ① iOS PWA 切回前台白屏/播放状态丢失已修复，用户真机确认。根因是 `LibraryIdentityBridge` 把游客 refetch 时 Better Auth 置位的 `isPending` 当成身份未知而卸载整个应用，现仅首次会话查询阻塞应用（#181）。② 登录页单屏化、邮箱主入口、Google/GitHub 并排，验证码流程用 `sessionStorage` 保存邮箱/步骤/冷却并在刷新或页面被丢弃后恢复且不自动重发（#182）；用户真机确认登录页与登录正常；“发码→切邮箱 App→返回”已验收：临时切出不再白屏，切出较久时 iOS 仍会丢弃页面并刷新一次（系统行为，不可避免），刷新后回到验证码界面，可继续输入登录。
7. **iOS 主屏幕 PWA 状态栏与底部白边（已修复，用户真机确认白边消失、顶部渐变更好看；已随 #192 发布 main `821aa59`，生产部署 READY）：** 顶部浅色带是 `statusBarStyle: "default"` 下 iOS 叠的近白雾面；已改 `black-translucent`（#186），首页/调频页过渡柔和，播放页顶部仍有雾面，**接受为 iOS 行为**（`theme-color` 在主屏幕 PWA 无效；改 fixed 图层 #187 无益，已撤销 #188）。该模式带来**底部白边**，真机诊断（诊断页已删）读数：`screen.height` 874，`innerHeight`/`100dvh`/`100svh`/`.app-root` 均 812（少了状态栏 62），`100lvh` 874；`fixed` 层同样停在 812。修复：主屏幕 PWA 下用 `100lvh` 作满屏高度——`tokens.css` 的 `--root-h/--app-h/--fixed-bottom/--fixed-h` 在 `(display-mode: standalone)` 或 `html[data-standalone]`（`layout.tsx` 用 `navigator.standalone` 设置）时切换，作用于 `html/body`、`.app-root`、`.sheet-layer`、`.install-layer`。新增满屏层/fixed 层时请用这些变量，不要直接写 `100dvh`/`inset: 0`。**正式版（wavecast.space）主屏幕图标需删除后重新添加**才会使用新状态栏样式。
8. **选曲/时长/语言/口播优化（#195，已合并 integration，2026-10-09 核对）：** 名字与重复歌曲识别、对上游的缓存/合并/熔断、调频失败的原因说明与「换个说法」、提案阶段的深层艺人兜底（#213）、可播放候选池（`WAVECAST_CATALOG_POOL`，默认关，[ADR 0022](adr/0022-playable-candidate-pool.md)）、按时长伸缩路线（`WAVECAST_DURATION_SCALING`，默认关）、显式节目语言 `output_language`。两个开关默认关，**未经用户试听，不要默认打开**。口播方面已合并：展示文本与播报文本分离（`spoken_form.py`：外语歌名读法、年份读法）、五台主持声线与不重复开场（`intelligence/voice.py`、`stations.py`；台标放在内容之后，夜里不口播）、Writer 一次有界改写与质量检查（`narration_quality.py`）、用量观测（`/api/episodes/{id}/usage`）。**口播与曲目一致（#222、#223）：** 请求点名的艺人（`required_artists`）必须进路线，漏了就从曲库补；补不上记为未兑现，口播不得提及；绑定后若实际播的是备选曲或章节文案写的是没在播的艺人，改用通用文案；Writer 一次改写后仍提到没放的艺人，丢弃该段。离线测试已覆盖；真实模型只验证了 1 档（Mogwai→Explosions in the Sky）。开发用 DeepSeek key 2026-10-09 返回 402 余额不足，继续实跑前需充值。未做：#201 TTS 表现、#202 多样性（含“不同演绎”的演奏者去重）、#204 后台生成；主持词精校草稿 `docs/design/host-voice-draft.md` 在分支 `docs/host-voice-draft`，未合并。已知口播问题：开场白仍有 AI 味，结尾偶有口号，末曲介绍与结尾会重复念同一句歌名。

## 已交付与边界

- Frost 前端：调谐窗/拨轮、开播流程、播放器、NowLine、主持文稿、三层进度、节目路线、常驻迷你条、首页/节目库、偏好弹层、PWA 安装引导、账户/登录、动效、电脑及安卓适配。主要设计依据：[HANDOFF](design/frost/HANDOFF.md)、[MOTION](design/frost/MOTION.md)；实际实现以 `apps/web` 为准。
- 播放逻辑在 `apps/web/lib/use-programme-playback.ts`；常驻 host 在 `apps/web/components/player/playback-provider.tsx`。离开播放页继续播放是已实现行为；浏览页面不等于结束收听会话。
- 封面 v2 已在 `apps/web/lib/cover/build-cover.ts`；五台配置在 `apps/web/lib/stations.ts`，每台三个候选模板、按 seed 参数化。五台为随便听 88.7、唱片行 93.1、人物志 97.4、来龙去脉 101.5、夜里 105.8。
- 电台选择目前是前端配置/关键词匹配，不能声称后端已按五台分别编排。P1 方案见 Frost HANDOFF 第 9 节，尚待独立任务验证实施。
- 登录推荐是 programme proposals；游客“先听这几档”是固定选题入口，点击后真实生成，并非预制 mock 音频节目。不要把所有固定选题等同于 mock。
- 封面/账户设计原稿部分未入 integration；以现有实现为准，不引用不存在的原稿链接。
- 纯 mock 音源带参数的渲染路径此前存在不能完整播放的问题；不能用注入假 manifest 的截图证明真实音频验收。

## 分支、部署与验证

2026-10-08 核对的 Git 状态（随下一次发布更新）；生产 Vercel `dpl_HzfZMFu8ZVkny1B7pRMAgPfRWg79` READY：

| 分支/PR | 状态 |
| --- | --- |
| `main` | `821aa59`，#192 release 合并提交（含 #179–#183 与状态栏/白边修复） |
| `integration` | 已快进到 `821aa59`，与 main 一致 |
| `feat/concept-film` / [#174](https://github.com/ZakuZakuu/wavecast/pull/174) | 独立宣传片 PR，未合并；head `3dc5145` |

正式 Web 由 Vercel 跟随 main，Railway API 为正式后端；用户已完成正式域名/OAuth/Railway 配置。邮箱验证码登录与上述修复已随 #180/#183 发布；后端无改动，Railway 未重新部署。部署运行规则及域名登录见 [runbook](deployment/railway-vercel.md)，CI 选择见 [ci.md](deployment/ci.md)。

开发：功能分支 → PR 到 integration → 合并后的托管预览验收 → release PR integration → main（普通 merge commit）→ integration 快进到 main 合并提交；不 force push。不为了获得预览把未验收工作推 main。integration/main 保留，保护长期分支，避免合并后自动删除 integration。

只有已知 Web/文档路径的 integration PR 自动跳过 backend 与 Docker smoke；Web 检查仍跑。main release 运行全量 CI。没有新 Claude 配置要求；不要通过 CI skip 指令节省额度。部署合并本身可能触发托管动作，应集中成完整验收点。

## 已知问题：事实与待查原因分开

2026-10-06 确认以下 issue 均 open：

| Issue | 现象与方向 |
| --- | --- |
| [#171](https://github.com/ZakuZakuu/wavecast/issues/171) | 缓冲充足仍显示“正在准备”。用户已决定初赛后统一处理。现有 preparingAhead 已含未完成且余量不足 45 秒；UI 混用 programBuffering/!audioReady，根因待复现。 |
| [#172](https://github.com/ZakuZakuu/wavecast/issues/172) | 人物志预估 42 分钟，完成后约 18 分钟。需核对目标、可用曲目、路线/终止条件和音频前缀显示口径；尚未证明“路线没走完”是根因。 |
| [#173](https://github.com/ZakuZakuu/wavecast/issues/173) | 中文界面出现长日文节目标题；封面无字是既有长标题降级。待明确中文标题与独立封面短标题（不超过 8 汉字）的合同及兼容。 |

Claude 另报告泛化章节名“第 N 段”、偶发播放错误及提示遮挡封面；目前仅为待复现反馈，未在本次核实为已建 issue 或已确认根因。先取得节目 URL/ID 和日志，不泛化为所有节目故障。

## 文档与协作入口

- `AGENTS.md`：仓库规则、文档管理与职责分工。
- 本文件：当前快照，保持短；历史原文已完整保存到 [历史归档](history/PROJECT_STATE-through-2026-10-02.md)，归档不是当前任务清单。
- `CODEX_HANDOFF.md` 是长期合同；Narration P0 和旧 Actions 故障为历史。
- `docs/adr/`：已决架构；设计规范放 `docs/design/`，部署操作放 `docs/deployment/`，提交材料放 `docs/submission/`。
- **Codex 负责整体规划、事实核对和统一状态；Claude 按单项任务实施。**交接给 Claude 时只传目标、相关文件/资产、约束、验收和交付方式，不让其重复梳理全部历史。实现者汇报差异与验证，Codex 汇总进本文件；不新建另一个 CURRENT_STATUS 或把会话全文塞进快照。
