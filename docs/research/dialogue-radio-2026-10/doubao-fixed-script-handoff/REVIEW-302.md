# #302 审查与修改任务

审查对象：`2505f75749b38bf7584282e82c0eb1f7fee1f9b1`，2026-10-15。
结论：暂不批准合并，先完成下面的修复与协议接线。此结论不是 GitHub 上已提交的 review。

直接相关的 `tests/test_doubao_podcast.py`、`tests/test_dialogue_runtime.py` 共 29 项通过。
以下复现全部为固定响应，无密钥、无网络调用；它们补充了现有全绿测试没有覆盖的边界。

## 1. 响应后失败漏记用量（必须修）

位置：`providers/doubao_podcast.py::synthesize_dialogue`。

`_storage.put` 在记录异常的 try 块之外；`_record("ok")` 在上传之后。
假传输成功返回音频，存储 `put` 抛 `OSError`：实际观察到 `transport_calls=1`，`usage_events=0`。
存储阶段取消也会走同样的账本缺口；响应校验失败则把已有 result 当成 None，丢掉已有回执。

要求：覆盖整次尝试，恰好一条最终用量事件；供应商已经返回的用量不能因应用端失败而丢失。
对接真实协议的音频 token 字段，明确已知/部分已知/未知；成本未知为 null，保留取消传播，不自动重试。
补成功后上传失败、上传取消、响应校验失败、部分 usage 后断流的测试，并验证安全投影保留计量字段。

## 2. 恢复前重复调用素材模型（必须修）

位置：`orchestration/dialogue_runtime.py::offer`。

目前先 `_material.extract`，之后才 `_seam.author` 检查预约与已保存稿件。
使用现有 `Rig` 完成一次 author 后，再 offer 同一 episode/slot/track：素材模型调用从 1 变为 2，Writer 与 checker 都仍为 1。
第二次没有预置素材假响应时，`offer` 返回 None，连现有已保存稿都无法取回，实际恢复会依赖一次多余付费调用。

要求：发模型请求前判断该块是否已存在、故事是否被其他块占用/已讲；按既有账本语义恢复或跳过。
已保存块恢复时不调用素材、Writer、checker；占用/已讲的故事不发新的素材请求。
重复请求与并发请求仍应服从已有预约约束，不要以“先读后写”绕开它。

同时检查快照的接线：`_seam.author` 恢复得到的 segment 可以携带 `dialogue_audio`，`offer` 当前只返回 `.dialogue`，会丢掉该 segment 上的快照。
正常 episode 持久化恢复已有覆盖；这里要求补的是“从已保存的对话 artifact 重新接入 authoring”的路径。
让已保存音频/快照沿该路径保留下来，并以改变当前音色设置后的恢复测试证明不重合成、不换声音。
这项是代码路径发现的风险，尚未独立端到端复现，不应把它写成线上已发生事故。

## 3. 编排失败没有回原 Writer（必须修）

位置：`assembly.py::StagedProgressiveChapterGenerator.author_narration`。

让 composer 仅对含 dialogue 的脚本抛 `NarrationPlacementError`，普通 Writer 脚本可正常通过。
实际观察到 `single_writer_calls=0`，章节口播为 `SKIPPED`；story 虽释放，原 Writer 路径没有执行。
这与本 PR 宣称的“任何失败都回原 Writer，只增加、不拿走原口播”不一致。

要求：对话构造/放置失败后先释放预约，再在仍有效的共同截止时间/预算内尝试原 Writer 一次。
取消不触发兜底，听众已越过/前缀已冻结也不触发兜底；没有预算时保持音乐连续并明确跳过。
不重试对话、不反复抽稿、不延长总截止时间。若普通 Writer 也失败，沿现有音乐优先降级。
补“只有 dialogue 编排失败、普通 Writer 成功”的回归测试，不能只测核对失败。

## 4. 用已有成功协议完成真实 transport（本批接完）

详见本目录 README、参考客户端和 framing helper。用 `DOUBAO_PODCAST_API_KEY` + 已成功的资源 ID；修正当前未验证的 App ID / Access Token 要求。
先支持已测的 PCM 收取、本地 WAV 封装；保留固定 B 声音、语速 0、逐轮对齐校验、零自动重试和取消传播。
正式配置、assembly 和 API 两处都要接正式 transport；关闭开关时继续不构造、不要求豆包密钥。
范围之外的能力不要写成已验证，示例客户端也不要直接作为生产实现导入。

## 5. 完成这一次接线的验收

新增“先经真实 HLS renderer 发布一段前缀，再完成迟到双人稿”的场景：已发布清单、分片内容和长度不回写；迟到稿不插入已冻结部分；故事预约正确释放/对账。
当前 #302 的 HLS 测试先 `_close_programme`，验证的是完整冻结节目，不能代替渐进播放中的上述竞态。
使用假 WebSocket、固定文本响应、真实本地音频封装与 HLS 渲染，不发付费调用。

在 #302 同一实现分支处理，更新 ADR 0027 / PROJECT_STATE，相关测试、ruff、mypy 后等最新 head 的 CI。
非渐进整档生成暂不扩展；开关默认关闭。不要先合并 #302，再另立“通信层接线”架构批次。
不改 main，不部署，不改生产变量；真实最小调用与试听另行安排。
