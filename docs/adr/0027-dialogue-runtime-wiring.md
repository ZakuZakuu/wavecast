# ADR 0027: 双人讲述接入运行时（第四批，默认关闭，固定响应与假音频）

- 状态：已实现并用固定响应、假 WebSocket 和假音频验证，**默认关闭**；真实豆包传输层已按 2026-10-14 成功实验的协议接入，**尚未做过真实调用**（真实最小调用与试听另行安排）；不改生产变量或部署
- 日期：2026-10-15
- 前置：[ADR 0024](0024-ark-text-models-and-dialogue-contract.md)、[ADR 0025](0025-story-material-and-checked-dialogue-path.md)、[ADR 0026](0026-dialogue-to-timeline.md)

## 目标

把前三批的模块接成一条真实运行的路径：**章节的检索证据 → 共享素材 → 双人稿 → 核对 → 配音 → NarrationSegment → 现有 HLS 渲染**，并且开关关闭时与之前完全一致。本批不新增无消费者的基础模块；新增的每个文件都有调用者。

## 决定

### 一、开关与配置（默认关闭）

| 变量 | 默认 | 含义 |
| --- | --- | --- |
| `WAVECAST_DIALOGUE_RADIO` | `off` | 总开关。关闭时不构造任何对话对象，物化器没有对话配音提供方，`author_narration` 的代码路径与之前一致 |
| `WAVECAST_DIALOGUE_SPEECH_PROVIDER` | `mock` | `mock`：不需要凭据的静音假音频；`doubao`：需要 `DOUBAO_PODCAST_API_KEY`（播客服务自己的 API Key，不是 App ID / Access Token，也不是 Ark 文本 Key） |
| `DOUBAO_PODCAST_RESOURCE_ID` | `volc.service_type.10050` | 成功实验用的资源 ID |

选 `doubao` 但缺 `DOUBAO_PODCAST_API_KEY`，**启动时**就以 `ProviderConfigurationError` 失败（不是等到第一段对话）。开关关闭时不构造、也不要求豆包密钥。文本模型沿用 ADR 0024 的角色配置（`material` / `writer` / `fact_check`），不新增模型名单。

### 二、接入点：先“提议”，失败就回到 Writer

`StagedProgressiveChapterGenerator.author_narration` 在原有流程（章节研究 `track_research.prepare` 之后）多做一步 **`DialogueRuntime.offer`**：

1. **资格**：只有“两首歌之间、只有一个槽位、不是开场也不是收尾”的章节可以带故事；电台的 `slot_share` 在这类槽位中按 seed 确定性地选出，可以一个也不选；`NIGHT` 没有预算，永远不选。没有选中的槽位**不发任何模型请求**。
2. **证据**：只用这一章的、已通过 ADR 0023 研究与核对的证据（章节计划里的证据 ID，加上本章曲目研究新找到的证据）。没有证据就不提议。
3. **故事**：`story_id` 由曲目引用确定性生成（同一首歌同一个故事，重试/恢复稳定）；块 ID 由槽位生成。
4. **流程**：`StoryMaterialService.extract` → `DialogueSeamService.author`（预约故事 → Writer → 核对/局部修复 → 保存存档）。
5. **成功**：得到的 `DialogueBlock` 放进一个单块 `RadioScript`，**走同一个 `assemble()`**（槽位放置规则、`compose_prepared`、“文本与时间线一致”断言都照常执行）。`_merge_writer_blocks` 对“恰好一个带对话的块”原样放行，只改 kind 和锚点；多个块、对话与其他块混合仍然拒绝。
6. **任何失败**（证据不足、素材不足、核对不通过、模型错误、存档失败）→ 返回 `None`，章节**完全按原来的 Writer 路径**写。取消不被吞掉；预约由 `DialogueSeamService` 释放。
7. **对话已做好但放置失败**（`NarrationPlacementError` 等编排错误）→ 先释放故事预约，再让原 Writer 写**一次**（对话不重试、不重抽）。只有在“当前章节仍可插入”时才兜底：听众已到达该章节、占位已因连续性被 `SKIPPED`、章节已被写过、监听者已离开，或被取消，都**不**兜底（不为没人会听的章节花钱）。判断读的是**当前**节目状态（`orchestration/authoring_gate.py`，由 `author_pending_narration` 在每章前打开，与 `_finish_authoring` 的判定一致）；没有打开闸门的调用方（测试、其他入口）不受影响。Writer 也失败 → 沿现有“音乐优先”降级。对话路径因此只能“多出一段”，不会“拿走原本会有的一段”。

### 二（补）：先问账本和存档，再问模型

`offer` 在发任何模型请求**之前**调用 `DialogueSeamService.resume`（只读判断，故事的取得仍然走 `author` 里的预约，并发时它才是权威）：故事被别的块占用 / 已讲 / 本块正在别处制作 → 直接跳过，不发素材请求；本块已存档**且身份一致**（故事 ID、槽位 ID、电台都与本次请求相同）→ 原样取回，**素材、Writer、核对者调用均为 0**，并把存档旁的音频请求快照带回片段；存档在但故事已退回池中（例如对账释放过）→ 经账本重新取得后取回，不重写。已讲的稿件永不再次进入。块 ID 只表示节目里的位置：同一位置若换成了另一首歌（路线变了），存档里的旧稿和旧音频**不复用**，也不为新歌留下预约，不覆盖旧存档，章节走 Writer 路径（`resume`、`author`、`_existing` 三处都核对）。取回的片段带 `dialogue_audio` 时，配音按快照**恢复**（零合成、原音色），不看当前配置。配音成功后，`materialize_pending_narration_async` 通过可选钩子 `record_dialogue_audio` 把快照写到存档旁（仅第一次，失败只记日志；episode 记录仍是权威）。

### 三、配音与快照

`NarrationMaterializer` 在装配和 API 两处都按同一份设置构造（`build_dialogue_voicing`）。进入 `SCRIPT_READY` 的对话片段由现有的 `materialize_pending_narration_async` 配音；**实际时长**写回片段。`_finish_narration_enrichment` 现在把 **`dialogue_audio`（请求快照）和资产一起写回 episode**——之前只复制资产三件套，快照会丢，之后的恢复就会退回当前配置。配音结果为 `SKIPPED`（不可读文字）时，片段记为 `SKIPPED`，不再被标成没有资产的 `AUDIO_READY`（对单人路径同样适用）。

episode 记录里的 `dialogue_audio` 是权威；存档旁的快照（`…audio.json`）是为“从已保存稿件重新接入 authoring”准备的副本，见上一节。

### 四、故事账本与对账

`StagedProgressiveRuntimeAdapter.settle_dialogue` 在每次 `author_pending_narration` 结束时调用 `DialogueRuntime.settle`：`reconcile`（到达听众 → 已讲；`SKIPPED` → 退回）加 `release_orphans`（预约了但片段没进时间线，例如听众先到了该章节 → 占位被 `SKIPPED`、对话被丢弃）。对账是尽力而为：失败只记日志，不影响编排。**前提**：同一集同一时刻只有一个 authoring（ADR 0026 已说明；对象存储没有比较并设置）。

### 五、豆包：适配器、传输层与用量

**传输层**（`providers/doubao_podcast.py::DoubaoPodcastWebSocketTransport`，帧编解码在 `providers/doubao_frames.py`，来源与许可见该文件头和 `docs/third-party/agentkit-samples-LICENSE`）按 2026-10-14 成功实验的协议实现，且只支持已验证的部分：`wss://openspeech.bytedance.com/api/v3/sami/podcasttts`；握手头 `X-Api-Key`、`X-Api-Resource-Id: volc.service_type.10050`、每次新的 `X-Api-Request-Id`；`StartConnection → StartSession(action=3，固定稿件，PCM 24 kHz 单声道 16 位，语速 0，固定音色，头尾音乐关闭，不返回 URL) → 立即 FinishSession`，然后逐轮收 `PodcastRoundStart(核对 speaker/text 与输入顺序一致) / PodcastRoundResponse(PCM，可多包) / PodcastRoundEnd(检查 is_error 与时长)`，`UsageResponse` 可穿插，`SessionFinished` 时必须没有未结束轮且完成轮数等于输入轮数，最后 `FinishConnection`。**零自动重试、零重连**；超时（建连 30 秒内、每次接收 60 秒、整次 600 秒，均可由调用方覆盖）、取消、畸形帧、压缩帧、未知事件、错误帧（只保留数字码）、文本/音色不一致、轮数不符都受控报错，**不会返回部分音频假装成功**；取消和任何失败都关闭连接。完整对话收齐之后，礼貌关闭（`FinishConnection`）失败**不**丢弃已计费的完整音频。本地护栏：累计音频超过 600 秒（可配置）即中止——这是本地保护，不是服务配额。

**适配器**把 PCM 在本地封成 WAV（逐轮起止由 PCM 字节数推导，**没有**服务端原生时间戳）；缓存键含音色、语速、格式（`wav`）、协议版本（`doubao-podcast-fixed-script-pcm24k-v1`）。只接受已验证的取值：语速 0、格式 `wav`；其他取值在发请求前报配置错误。未支持并且未声称验证的：服务端直出 MP3/WAV、其他语速、重连/续传、原生时间戳。

**用量**：每次**真实尝试恰好一条最终事件**，不论成功、服务失败、响应校验失败、存储失败还是取消（`finally` 中记录）。服务已经返回的用量不因应用端失败而丢失：`input_text_tokens`、`output_audio_tokens`（供应商的计数；未报告为 `null`，报告的 0 保持 0）、`usage_status`（`complete` 会话完成且两项都有 / `partial` / `unknown`）、`outcome`、`failed_stage`、`rounds_completed`、`audio_seconds`、`sent_characters`（本地发送字数，不是计费）。成本未知记为 `cost_basis=unpriced`（计入 `cost_unknown_calls`），不是 0，也没有新增价格常量。计数只接受有限、非负、非布尔的整数。配音调用归属到节目：渐进配音（`materialize_pending_narration_async`）和 API 单片段入口都在 `usage_scope(episode_id)` 内调用，成功、失败、取消的事件都带节目 scope，按节目查询（`/api/episodes/{id}/usage`）只包含该节目；API 的物化器与渐进运行时共用同一个账本（`websockets` 现已显式声明为直接依赖并更新 `uv.lock`）。诊断投影（`safe_usage_event`）和总计（`UsageTotals.input_text_tokens / output_audio_tokens / usage_incomplete_calls`）都带上这些字段；不记录正文、请求体、原始响应、认证头或 URL。

## 验收对照

| 验收点 | 如何验证（`tests/test_dialogue_runtime.py`、`tests/test_doubao_podcast.py`） |
| --- | --- |
| 默认关闭、行为不变 | 默认设置下 `dialogue_runtime is None`，物化器没有对话配音 |
| 选中的槽位得到核对后的双人稿，Writer 不被调用 | 片段带 `dialogue`，`narration_text` 与之一致，Writer 调用 0 次；存档已保存，故事为 RESERVED，授权阶段不合成音频 |
| 未选中/夜间/开场/收尾 | 未选中的槽位 0 次模型调用，走 Writer |
| 核对失败回到 Writer 并退回故事 | Writer 调用 1 次，账本没有该故事 |
| 声音映射、实际时长、快照落到 episode | 配音后 `actual_duration_seconds` 为音频时长（3 秒，不是 40 秒估算），`dialogue_audio` 随 episode 保存并相等 |
| 迟到不污染 | 听众先到的章节：对话被丢弃，故事退回 |
| 对账 | 到达 → PUBLISHED；孤儿预约 → 退回 |
| 真实 HLS 路径 | 固定响应 + 假音频 → `author_pending_narration_async` → `materialize_pending_narration_async` → `POST /api/episodes/{id}/program-render` → 播放列表与分片可取；渲染不改 episode；同一请求重复得到同一清单；相对跳过该片段的同一节目，前沿长度恰好多出约一段对话的时长 |
| 启动失败 | `doubao` 缺 `DOUBAO_PODCAST_API_KEY` → 启动时报配置错误；有密钥则接上正式传输层；设置与 `repr` 不泄露密钥 |
| 适配器与用量 | 成功后上传失败 / 上传取消 / 响应校验失败 / 部分用量后断流 / 取消：每次恰好一条最终事件，已知计数保留，未知为 null；报告与总计带新字段；缓存键、WAV 封装、未验证取值被拒；经物化器配音与恢复（第二次零请求） |
| 传输层（假 WebSocket） | 握手头、事件顺序与 StartSession 载荷；整段对话收齐；握手 401/403/429/其他、错误帧只留数字码、文本/音色/轮数不符、孤立音频、轮错误、时长不符、未知事件、非二进制、坏 JSON、连接/会话失败、提前结束、中途断开、静默超时、总超时、取消关闭、音频护栏；礼貌关闭失败不丢完整音频；均只连接一次 |
| 同槽位换歌 | 存档属于另一首歌/另一电台/另一槽位时：不复用旧稿或旧音频、不留预约、旧存档与旧音频快照不变、0 次模型调用、走 Writer；原有同曲目恢复仍是 0 次调用 |
| 用量归属 | 渐进配音与 API 单片段入口：成功、失败、取消都计入该节目且没有无归属事件；另一个节目的用量查询为 0；API 物化器使用运行时的共享账本 |
| 恢复不重复花费 | 已存档：再次提议 0 次模型调用；全新进程、无脚本模型也能取回；故事被占用/已讲/他处制作 → 跳过且 0 次请求；改了当前音色后仍按存档快照恢复（零合成、原音色、同一资产）；故事被退回后经账本重取而不重写 |
| Writer 兜底 | 只有对话放置失败、普通 Writer 成功 → Writer 恰好 1 次，对话不重试，故事先退回；听众已到达 / 占位已跳过 → 不兜底；取消 → 不兜底；Writer 也失败 → 音乐继续 |
| 渐进 HLS：迟到稿 | 渐进节目先经真实 program-render 发布越过宿主缝的前缀；双人稿此时才写完：已发布清单和分片逐字节不变且只追加、迟到稿不插入、片段保持 SKIPPED、故事预约释放、没有合成 |

## 仍未覆盖

- **真实豆包服务的当下行为**：传输层只用假 WebSocket 验证，没有真实调用；真实最小调用与试听另行安排。服务端 MP3/WAV 直出、原生时间戳、价格未验证，也未支持。未知事件一律报错（按交接文档），第一次真实调用若出现实验中没见过的良性事件会失败，届时再按实际放行。
- **真实模型**的素材/稿件质量与 Ark 对这些结构化 schema 的接受度（ADR 0025）。
- **整档生成路径**（非渐进的 `assemble`）仍拒绝对话；对话只在渐进的 `author_narration` 中出现。
- **并发**：同一集的 authoring 必须是单写者；故事账本在多进程下没有比较并设置。
- **API 手动物化端点**（`/segments/{id}/materialize`）能为对话片段配音（同一份设置、记入同一个共享账本、归属该节目），但不写存档旁的快照副本。
- 朗读转换（读音/专名）、播放器展示、对话放在歌曲之间之外的位置。
