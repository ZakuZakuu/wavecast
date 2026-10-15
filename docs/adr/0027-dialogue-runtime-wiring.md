# ADR 0027: 双人讲述接入运行时（第四批，默认关闭，固定响应与假音频）

- 状态：已实现并用固定响应、假音频验证，**默认关闭**；真实豆包传输层**不在本批**（缺少可依据的线协议），不调用付费 API，不改生产变量或部署
- 日期：2026-10-15
- 前置：[ADR 0024](0024-ark-text-models-and-dialogue-contract.md)、[ADR 0025](0025-story-material-and-checked-dialogue-path.md)、[ADR 0026](0026-dialogue-to-timeline.md)

## 目标

把前三批的模块接成一条真实运行的路径：**章节的检索证据 → 共享素材 → 双人稿 → 核对 → 配音 → NarrationSegment → 现有 HLS 渲染**，并且开关关闭时与之前完全一致。本批不新增无消费者的基础模块；新增的每个文件都有调用者。

## 决定

### 一、开关与配置（默认关闭）

| 变量 | 默认 | 含义 |
| --- | --- | --- |
| `WAVECAST_DIALOGUE_RADIO` | `off` | 总开关。关闭时不构造任何对话对象，物化器没有对话配音提供方，`author_narration` 的代码路径与之前一致 |
| `WAVECAST_DIALOGUE_SPEECH_PROVIDER` | `mock` | `mock`：不需要凭据的静音假音频；`doubao`：需要 `DOUBAO_APP_ID` / `DOUBAO_ACCESS_TOKEN` / `DOUBAO_RESOURCE_ID` **和**一个传输层 |

选 `doubao` 但缺凭据，或没有传输层，**启动时**就以 `ProviderConfigurationError` 失败（不是等到第一段对话）。目前没有真实传输层，所以 `doubao` 暂时一定会被拒绝。文本模型沿用 ADR 0024 的角色配置（`material` / `writer` / `fact_check`），不新增模型名单。

### 二、接入点：先“提议”，失败就回到 Writer

`StagedProgressiveChapterGenerator.author_narration` 在原有流程（章节研究 `track_research.prepare` 之后）多做一步 **`DialogueRuntime.offer`**：

1. **资格**：只有“两首歌之间、只有一个槽位、不是开场也不是收尾”的章节可以带故事；电台的 `slot_share` 在这类槽位中按 seed 确定性地选出，可以一个也不选；`NIGHT` 没有预算，永远不选。没有选中的槽位**不发任何模型请求**。
2. **证据**：只用这一章的、已通过 ADR 0023 研究与核对的证据（章节计划里的证据 ID，加上本章曲目研究新找到的证据）。没有证据就不提议。
3. **故事**：`story_id` 由曲目引用确定性生成（同一首歌同一个故事，重试/恢复稳定）；块 ID 由槽位生成。
4. **流程**：`StoryMaterialService.extract` → `DialogueSeamService.author`（预约故事 → Writer → 核对/局部修复 → 保存存档）。
5. **成功**：得到的 `DialogueBlock` 放进一个单块 `RadioScript`，**走同一个 `assemble()`**（槽位放置规则、`compose_prepared`、“文本与时间线一致”断言都照常执行）。`_merge_writer_blocks` 对“恰好一个带对话的块”原样放行，只改 kind 和锚点；多个块、对话与其他块混合仍然拒绝。
6. **任何失败**（证据不足、素材不足、核对不通过、模型错误、存档失败）→ 返回 `None`，章节**完全按原来的 Writer 路径**写。取消不被吞掉；预约由 `DialogueSeamService` 释放。对话路径因此只能“多出一段”，不会“拿走原本会有的一段”。
7. 对话已做好但放置失败 → 释放故事预约，章节保持无旁白（与 Writer 失败时相同的语义）。

### 三、配音与快照

`NarrationMaterializer` 在装配和 API 两处都按同一份设置构造（`build_dialogue_voicing`）。进入 `SCRIPT_READY` 的对话片段由现有的 `materialize_pending_narration_async` 配音；**实际时长**写回片段。`_finish_narration_enrichment` 现在把 **`dialogue_audio`（请求快照）和资产一起写回 episode**——之前只复制资产三件套，快照会丢，之后的恢复就会退回当前配置。配音结果为 `SKIPPED`（不可读文字）时，片段记为 `SKIPPED`，不再被标成没有资产的 `AUDIO_READY`（对单人路径同样适用）。

按需的独立存档快照（`…audio.json`）在这条路径上**不写**：episode 记录里的 `dialogue_audio` 是权威，配音只发生在片段插入 episode 之后，没有“有音频、无片段”的窗口。`voice_segment` / `restore_narration_segment` 仍可用于需要时。

### 四、故事账本与对账

`StagedProgressiveRuntimeAdapter.settle_dialogue` 在每次 `author_pending_narration` 结束时调用 `DialogueRuntime.settle`：`reconcile`（到达听众 → 已讲；`SKIPPED` → 退回）加 `release_orphans`（预约了但片段没进时间线，例如听众先到了该章节 → 占位被 `SKIPPED`、对话被丢弃）。对账是尽力而为：失败只记日志，不影响编排。**前提**：同一集同一时刻只有一个 authoring（ADR 0026 已说明；对象存储没有比较并设置）。

### 五、豆包适配器：传输层可注入

`providers/doubao_podcast.py` 负责应用需要的部分：缓存键（含音色、语速、格式、协议版本）、存储、**每个结果（成功/失败/取消）一条用量记录**（只含次数、字符数、结果，不含文本）、速度与格式范围检查、错误映射、响应校验（空音频、格式不符、无时长、时间戳数量不符都拒绝）。**怎么向服务提问**是 `PodcastTransport`（注入）。固定稿件模式（action=3）的线协议没有可依据的公开文档，本批**不猜**；真实传输层要等一次带录制的实验再写（需要请求/响应样本、音频格式、时间戳与用量字段）。

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
| 启动失败 | `doubao` 缺凭据/无传输层 → 启动时报配置错误；设置不泄露令牌 |
| 适配器 | 假传输层：脚本逐行带各自音色、缓存键随音色/语速/格式/文字变化、用量记录、失败映射、取消、响应校验、经物化器配音与恢复（第二次零请求） |

## 仍未覆盖

- **真实豆包传输层**与真实音频（mp3）、时间戳、计费的行为；没有它，`doubao` 不能启用。
- **真实模型**的素材/稿件质量与 Ark 对这些结构化 schema 的接受度（ADR 0025）。
- **发布前缀**：本批的 HLS 测试渲染的是已完成的节目；渐进渲染下“迟到对话不进入已冻结前缀”继续由 ADR 0026 的指纹/`_finish_authoring` 测试与既有 program-render 测试覆盖，没有新增端到端的渐进场景。
- **整档生成路径**（非渐进的 `assemble`）仍拒绝对话；对话只在渐进的 `author_narration` 中出现。
- **并发**：同一集的 authoring 必须是单写者；故事账本在多进程下没有比较并设置。
- **API 手动物化端点**（`/segments/{id}/materialize`）能为对话片段配音（同一份设置），但不写独立的快照存档。
- 朗读转换（读音/专名）、播放器展示、对话放在歌曲之间之外的位置。
