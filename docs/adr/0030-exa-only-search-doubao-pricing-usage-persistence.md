# ADR 0030: Exa-only 检索配置、豆包自动估价、用量事件持久化

- 状态：已实现（离线验证）。三件事互相独立，为明早的完整节目验收而一并收尾；不新增统计后台或通用框架。
- 日期：2026-10-15
- 前置：[ADR 0027](0027-dialogue-runtime-wiring.md)（用量事件与账本）、[ADR 0029](0029-drop-post-hoc-check-from-default-dialogue-path.md)

## 一、Exa-only 检索

- 一个设置：`WAVECAST_SEARCH_BACKEND` = `exa_tavily`（默认，行为不变）或 `exa`。
- `exa` 时：不构建 Tavily、不读取 Tavily key；“精确检索”槽位复用同一个 Exa 客户端，`deep_research=None`。快速阶段（1 个发现 + 1 个检索查询）、背景阶段（意图上限不变：发现 ≤N、检索 ≤M，全部走 Exa）、按曲研究（`TrackResearchService`）都因此只请求 Exa。**没有任何自动切换机制**：想用 Tavily 就改设置。
- 记录反映实际供应商：快速/背景服务新增 `research_label`（`exa` 时失败信息写 “exa unavailable”，trace 的 `selected_queries[].provider` 写 `exa`）；背景规划提示词在 `exa_only` 时写明“全部通过 Exa 执行”，不再提 Tavily。默认配置下提示词逐字不变。
- Exa 价格由供应商回执的 `costDollars.total` 记录（实际收费，美元）。

## 二、豆包自动估价

输入文本 ¥120 / 百万 token，输出音频 ¥100 / 百万 token。从回执计数计算，不用字数；报告的 0 保持 0；缺失或会话未完成则费用未知。事件带 `price_version=doubao-podcast-2026-10-15`、`cost_basis`。详见 ADR 0027 末节。

## 三、用量事件持久化

- 现有 `UsageEvent` 增加 `event_id`；`UsageLedger.attach_sink(...)` 让每个**带 scope 的**事件同时写入对象存储（`usage-events/{scope}.json`，每个 scope 一份、最多 1000 条、`schema_version=1`，读改写加按 scope 的锁——与 `story_usage` 同一模式，同一集单写者）。写入失败只记日志，不影响任何供应商调用；没有运行中的事件循环时该事件只留在内存。
- 补齐此前不留痕的情形：Exa / Tavily 的**请求失败**和**取消**现在各记一条事件（`outcome=error|cancelled`、`error_type`、`stage`，费用与积分为 `None`，`cost_basis=no_receipt`）；成功事件带 `outcome=ok`。（Ark 与豆包本来就记失败和取消。）
- `GET /api/episodes/{id}/usage`（改为 async）合并进程内账本和存储里的副本，**同一 `event_id` 只算一次**，因此进程重启后仍可读，也不会重复计费；缓存/恢复的片段不产生新事件。响应在原有 `providers`（阶段、模型、调用结果、token、耗时、每条事件）之外新增：
  - `costs`：按币种分开——CNY 估算（Ark、豆包）、USD（Exa 实际收费）、检索积分（Tavily）；`unknown_calls` 单列没有任何费用数字的调用（失败请求、缺回执），不记为 0；币种从不换算。
  - `stored_events`：存储里读到的条数。
- 存储用 API 已有的 `audio_storage`（同一个根目录/卷），不新增服务或表。

## 未覆盖

- 多进程同时写同一集的事件仍可能丢更新（没有比较并设置）；同一集单写者。
- 供应商没在回执里给价格的调用（如未带 `costDollars` 的 Exa 成功响应）会被列为“未知”。
- 其他供应商（DeepSeek、MiniMax）的失败/取消事件不在此批范围内。
