# ADR 0024: Ark 文本模型、按角色配置模型、双人稿件契约（第一批，离线）

- 状态：第一批已实现（未接入整档生成、TTS、播放器，也未启用于生产）
- 日期：2026-10-14
- 关联：[接入设计](../design/researched-dialogue-radio.md) §3–6、§10；[实验报告](../research/dialogue-radio-2026-10/)

## 背景

实验里认可的是更完整的双人讲述。要让它进入生成链路，先要三块基础：能调用 Ark 的严格结构化输出；Writer 能单独换模型而不连带事实核对和曲目调研；有一个不依赖供应商的双人稿件类型。这批只建这三块，并用固定响应验证，不调用付费服务。

## 决定

### 一、Ark 适配器（`providers/ark.py`）

- 按实验验证过的请求发送：Chat Completions、`response_format = json_schema` 且 `strict: true`、`thinking` 关闭（经 `extra_body`）、`temperature 0.7`、`stream false`、`max_completion_tokens`。只有 Lite Writer 做过 strict 实测；Pro、Flash 的提案实验用的是 `json_object`。本批**不声称**三种模型都通过了 strict。
- 调用方传入的 `transport` 和 `InferenceProfile` 的 `reasoning_effort` 不转发给 Ark（现有调用点传的是 Responses 传输；Chat 参数也不能原样放进 Responses）。档位只决定超时和输出上限。FAST 档 15 秒/2048 的上限是按 DeepSeek 定的，而实测 Ark 提案和写稿需要 22–55 秒，所以 FAST 与 BALANCED 一样用 `ARK_TIMEOUT_SECONDS`（60）与 `ARK_MAX_OUTPUT_TOKENS`（4096），DEEP 与 CURATOR 用 100 秒与 12288。调用方自己的截止时间仍然有效。
- **每次只发一次。** SDK 重试关闭；超时、429、5xx、格式不合都不重发，不切 `json_object`，不换模型。需要重试时由调用方带着自己的预算决定。DeepSeek 适配器行为不变。
- 错误只按 HTTP 粗分：401 认证、403 权限（`ProviderPermissionError`，是认证错误的子类）、429 限流、5xx 不可用、其他 4xx 请求错误（`ProviderRequestError`）。不解释厂商错误码，也不凭空建立“余额耗尽”“模型未开通”“schema 被拒”的映射——没有真实错误体可依据。
- 响应返回之后的应用校验失败（漏字段、多字段、非 JSON、`length` 截断、非 `stop`）都是**响应错误**，不是 HTTP 错误；这些调用已经计费，用量照常记录。

### 二、供应商 schema（`providers/strict_schema.py`）

应用继续用完整 Pydantic 模型校验；发给供应商的是另外生成的 schema：去掉 `default`、`title`、`description`、长度和数值约束（它们由 Pydantic 在响应后执行），递归把对象的属性全部列为必填并设 `additionalProperties: false`，保留类型、枚举、`$ref/$defs` 和 nullable（可选值仍是“允许 null”，不会变成必须非空）。只处理 schema 关键字，名为 `title`/`default` 的业务属性不受影响，输入 schema 不被修改。遇到没有明确策略的结构（`pattern`、`format`、`oneOf`、自由形式的对象或映射、非本地 `$ref`）在发送前本地报错，不删除后继续请求。

完整 `RadioScript` schema 目前只证明**本地可转换**，Ark 是否接受它尚待一次最小真实调用确认。

### 三、按角色配置模型

八个角色：`proposal`、`fast_start`、`research_plan`、`material`、`curator`、`writer`、`fact_check`、`track_research`。每个角色有自己的选择器（`mock|deepseek|ark|inherit`）和 Ark 模型（`ARK_<ROLE>_MODEL`，没有默认值：模型 ID 带日期，且只在绑定 Ark 时才需要）。

- `inherit` 保持旧行为：`research_plan` 跟随 research 能力；`fact_check`、`track_research` 以前与 Writer 共用一个模型，现在**跟随基础配置**——显式 `mock/deepseek` 的 Writer 仍然带着它们（与旧行为一致），**Ark 的 Writer 不会**。所以 Writer 换成 Lite 时事实核对和曲目调研不变。
- 首页推荐（`WAVECAST_RECOMMENDATION_PLANNER=ark`）和主动提案（`WAVECAST_PROPOSAL_PLANNER=ark`）共用 `proposal` 角色的模型，各自保留模式和提示词；推荐的 `source` 标记为 `ark_planner`。
- `material`（整档共享的故事材料提炼）本批只有配置位，**还没有消费者**，不为用上它新增调用。
- 只有角色真的解析为 Ark 时才要求密钥和模型；未启用的 Ark 配置不会让服务启动失败。默认仍是 mock/DeepSeek。

### 四、双人稿件契约（`models/dialogue.py`、`providers/speech.py`）

- `DialogueTurn`：逻辑说话人 `A/B`、`text`、可选 `tts_text`、必填的 `fact_refs`（可以为空）。`DialogueDraft` 是模型输出（只有 turns）；`DialogueBlock` 加上稳定的 `block_id`、`slot_id`、`purpose`、时长，由应用赋值。
- `dialogue` 是正文来源：`RadioScriptBlock.dialogue` 存在时，`text`/`tts_text`/时长由它**派生**，给出不同的值会被拒绝；没有说话人标签，所以拼出的单人文本不会把 A/B 读出来。该字段不进 JSON schema，单人 Writer 的提示和 schema 不变。
- `fact_refs` 的含义是“本轮用了哪些素材事实”。它与 `Evidence.id` 是两个命名空间，不混用：第一批由调用方传入允许的 ID 集合校验（`intelligence/dialogue.py`），未知 ID 失败；`story` 用途的块至少要有一条引用，开场、过渡、结尾可以全空；校验从不替模型补引用。事实 ID 到证据 ID 的映射属于第二批的素材对象。结构合法不等于事实被支持，那是事实核对的工作。
- `SpeechRequest`：单人文本，或有序对话加每个说话人的声音快照（不透明的 `voice_id`）。逻辑角色与厂商声音分离；没有适配器消费它，TTS 协议仍是字符串。音色 B 的映射（A=刘飞，B=潇磊，语速参数 0）留给配音批次。

### 五、用量与成本

- Ark 的 USD 字段保持为空，人民币估价放进事件 metadata：`estimated_cost_cny`、`estimated_cost_cny_low/high`、`cost_basis`、`price_version`。价格是 2026-10-14 实验回执里的费率，不是合同报价，也未计试用额度。未知模型或缺少 token 数，费用为**未知**（null），不是 0；缓存拆分缺失时按全价作上界并标明。
- Flash 的价格随高峰/空闲时段不同，没有永久常量：只给区间（空闲价为下界，高峰价为上界）。
- 安全诊断投影保留这些字段，汇总里有 `estimated_cost_cny`、区间和 `cost_unknown_calls`；既有的 USD 小计**不包含 Ark**，本批不改造多币种报表。
- 超时、取消、HTTP 错误、连接失败各记一条事件：耗时、是否已发出请求（`request_dispatched`）、是否收到响应、用量是否已知；拿不到回执就标记用量与费用未知。已经拿到响应但应用校验失败的调用，记录真实 token。取消会重新抛出 `CancelledError`。

## 兼容性

DeepSeek/mock 的默认和行为不变；旧单人 `RadioScriptBlock` 的字段、序列化和提示 schema 不变（`dialogue` 为 `null`）。`ProviderSettings` 新增的字段都有默认值。

## 本批没有覆盖：持久化与恢复

转成播放片段的路径还不能携带对话：`NarrationSegment` 只有一份 `narration_text/tts_text`，没有说话人、轮次或事实引用。因此两处会**显式拒绝**对话，抛出 `DialogueNotSupportedError`，而不是静默压平为文本：

- `composer._narration_segment`（块到片段）；
- `assembly._merge_writer_blocks`（合并多个 Writer 块）。

其他会改写 `text` 的 `model_copy` 路径（例如把台标拼到最后一块）没有逐一加防护：目前没有任何路径会产生对话块，加防护要等对话真正进入生成链路时一起做。

这意味着双人路径目前只能在内存里的稿件对象上校验，不能进入整档生成。后续批次需要：

1. 给 `NarrationSegment`（或其旁的资产记录）增加带版本的对话字段，并明确旧数据读取、新数据回滚时的行为（`schema_version`）；
2. 恢复时从持久化的轮次、角色快照重建，而不是重新写稿或重新合成；
3. 缓存键包含有序轮次、角色与声音映射、供应商/模型、语速、格式和协议版本；
4. 整段对话仍作为**一个**音频资产交给时间线，已发布前缀不可变的规则不变。

`ProgressiveAssemblySession`（`schema_version: 1`）只记录哪些章节已写过，不含稿件，所以这批没有改动它。

## 仍未验证

- Ark 对完整 `RadioScript`/`DialogueDraft` 规整 schema 的真实接受情况；Pro、Flash 的 strict 行为；`thinking` 以外档位的行为。
- 真实的余额耗尽、模型未开通、schema 被拒的错误体（本批测试用明确标为合成的夹具）。
- 价格版本以外的真实账单。
