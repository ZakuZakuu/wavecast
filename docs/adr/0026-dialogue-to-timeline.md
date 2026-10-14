# ADR 0026: 检查后的双人讲述进入现有时间线（第三批，离线）

- 状态：第三批已实现并用假音频验证；**未接入整档生成、真实配音供应商、播放器**，不调用付费 API，不改生产变量或部署
- 日期：2026-10-14
- 前置：[ADR 0024](0024-ark-text-models-and-dialogue-contract.md)（对话契约；转片段的限制）、[ADR 0025](0025-story-material-and-checked-dialogue-path.md)（素材、核对、保存）

## 目标

接通 `核对后的稿件 → SpeechRequest → 配音资产 → 缓存 → NarrationSegment → 现有时间线`，并在这条路径验证过之后解除 ADR 0024 对“对话转播放片段”的限制。旧的单人路径不变。

## 决定

### 一、对话作为片段的内容（解除限制）

`NarrationSegment` 新增可选字段 `dialogue`（完整的 `DialogueBlock`：轮次、说话人、`fact_refs`、块/槽位 ID、`story_id`）和 `dialogue_voices`（本段音频实际使用的“说话人→声音”快照）。有 `dialogue` 时，`narration_text` 由它派生，给出不同的值被拒绝；`tts_text` 和 cues 属于单人路径，与对话并存被拒绝。对话随片段一起经过 JSON 往返（仓库就是这样存片段的），不再需要另找地方放轮次。

`composer._narration_segment` 不再拒绝对话块，而是把它带进片段。`assembly._merge_writer_blocks` **仍然拒绝**对话块：把对话和别的文字合并成一段没有定义。

### 二、配音：一个接口、一个资产、一个缓存键

- `SpeechRequest`（ADR 0024）→ `DialogueSpeechProvider.synthesize_dialogue()`，整段对话产出**一个**音频资产，其**实际**时长写入片段的 `actual_duration_seconds`，编排按它规划（不是按估算）。
- 声音映射是配置，不在对话里：`providers/doubao_voices.py` 记录用户选定的 B 组合（A=刘飞 `zh_male_liufei_v2_saturn_bigtts`，B=潇磊 `zh_male_xiaolei_v2_saturn_bigtts`，语速 0），只是配置，没有适配器、没有网络。语速 0 属于豆包自己的刻度，与 MiniMax 的 0.9 不可比。
- 缓存键覆盖：有序的（说话人，文字）、每个说话人的声音、供应商与模型、语速、格式、协议版本。换声音或改一个字不会复用旧音频；同一段、同一映射重复请求不会再合成。
- `NarrationMaterializer` 可选地接受对话配音提供方和声音映射；**没有配置时对话片段抛配置错误**，不会退化成用单人声音把对话读出来。单人路径的代码和行为没有改。

### 三、保存后恢复：不重写、不重新核对、不重新合成

核对后的稿件（ADR 0025 的 `CheckedDialogueRecord`）是权威存档；`restore_narration_segment()` 从存档重建片段，再交给物化：音频已在存储里就是缓存命中，**零次模型调用、零次合成**。已经 `AUDIO_READY` 的片段本来就不会再物化。

### 四、取消、迟到、失败不动已发布前缀

对话片段就是普通的 `NarrationSegment`，所以现有的保护原样适用，并有测试覆盖：

- 合成失败或被取消：片段回到 `SCRIPT_READY`，没有资产、没有时长，可以重试（取消时也重置，这一点对话路径比单人路径更严）。
- 听众已到达该章节：`_finish_authoring` 不会插入迟到的对话（占位变为 `SKIPPED`）。
- 迟到的配音结果：基于旧快照的保存因版本冲突失败（`EpisodeConcurrencyError`），仓库里仍是已放弃的 `SKIPPED` 状态，没有音频。
- 已发布部分的混音指纹：加入对话前后，发布前缀的 `mix_plan_fingerprint` 不变。

### 五、素材的预约/发布/取消（避免重复讲述）

`StoryUsageLedger`（每集一份带必填 `schema_version` 的 JSON）：故事**可用 → 预约（RESERVED，由一个块持有）→ 已讲（PUBLISHED，不可逆）**，取消/跳过/失败时预约退回可用。`DialogueSeamService.author()` 先预约，再跑流水线并保存存档；流水线拒绝、保存失败或被取消（包括取消）都会释放预约；已被占用或已讲过的故事不花任何模型调用，直接 `story_already_used`。`reconcile()` 按片段状态更新：进入 `COMMITTED/PLAYED` 记为已讲，`SKIPPED` 的预约退回；`release_orphans()` 处理崩溃留下的孤儿预约（只在没有进行中的 authoring 时调用）。

## 验收对照

| 验收点 | 如何验证 |
| --- | --- |
| 轮次和 B 音色映射不丢失 | 请求里轮次顺序与说话人逐一对应；声音快照在片段、存储元数据里；JSON 往返后仍在；对话本身不含声音 ID |
| 实际音频时长参与编排 | 88 秒的固定音频 → 片段时长 88，混音片段的可播放时长 88，后一首随之后移 |
| 保存后恢复无需重写或重合成 | 新 store/新 provider 只共享存储：合成 0 次，Writer/核对者模型调用数不变，资产与时长相同 |
| 取消、迟到、失败不修改已发布前缀 | 见上节四项 |
| 不重复讲述 | 第二个块拿不到已被占用的故事、不花模型调用；拒绝/取消释放；已讲不可再预约或释放；孤儿预约可退回 |

## 仍未覆盖，需要真实接口或后续接线

- **真实豆包适配器**：本批只有契约和假音频。真实请求格式（固定稿件模式）、音频格式（mp3）、逐轮时间戳的真实形状、整段超时/取消/迟到时的真实计费，都未验证。真实适配器应像 Ark 适配器那样为失败和取消记录费用未知的用量事件；假提供方没有写用量账本。
- **接线**：装配（`create_episode_assembly_service`）还没有配置对话配音提供方；`author_narration` 还不会调用素材/流水线；`DialogueSeamService` 没有被运行时调用。所以真实生成链路里不会出现对话。
- **真实渲染**：前缀稳定用混音指纹和 `_finish_authoring` 验证，没有跑 HLS 渲染工作线和 `_canonical_render_plan`。
- **朗读转换**：Writer 不能提供 `tts_text`（ADR 0025）；读音、专名的确定性转换尚未做。
- **并发**：对象存储没有比较并设置，账本的读改写只在同一进程内串行（每集一把锁）；多进程需要数据库行加版本号。
- **接口暴露**：`LiveEpisode` 的 JSON 现在会多出 `dialogue`、`dialogue_voices`（含 `fact_refs`）；前端会忽略未知字段，但没有逐一检查。数据库里的旧记录读取不受影响（字段可选），新记录被旧版本代码读取则不保证。
- 对话与演唱重叠的混音策略、对话放在歌曲之间之外的位置、数据库表。
