# 豆包固定稿双人配音：实测协议交接

整理日期：2026-10-15。供 #302 后续接线使用；本次整理和审查没有调用付费 API。

这份资料来自 2026-10-14 已成功的 WaveCast B 音色实验客户端和安全用量摘要。
它证明该次调用成功，不代表当前服务的所有模式、参数范围或错误形状都已验证。
不要再以“缺少实验请求代码”为理由猜协议，也不要把这里的演示预算当作供应商限制。

## 目录与来源

- `call_podcast.py`：历史成功客户端，默认 dry-run，只有显式 `--live` 才联网。仅移除了全局禁用日志的操作。
- `protocols/`：该客户端实际使用的二进制帧帮助代码。保留编解码，去掉正文/错误体日志和诊断中的 payload；来源和修改见 `NOTICE.md`、`LICENSE`。
- `source-hashes.json`：整理前本地原文件的 SHA-256。原实验未记上游 commit，不能假称已锁定某个上游版本。
- `dialogue.json`：相同结构的无事实示例，正文已换成两句普通过渡语，**不是历史成功请求的原正文**。
- `historical-receipt.safe.json`：历史 B 实验回执的安全投影。没有密钥、会话 ID、原始响应、音频 URL 或稿件正文。
- `REVIEW-302.md`：审查结论、离线复现结果和本批修改要求。

上游帮助代码来源：[bytedance/agentkit-samples](https://github.com/bytedance/agentkit-samples)，Apache-2.0。
官方产品文档入口：[播客语音合成](https://www.volcengine.com/docs/6561/1668014?lang=zh)；本次抓取未成功，下面的线协议依据历史成功客户端，不声称来自本次在线逐字核对。

## 已成功调用的请求

连接：`wss://openspeech.bytedance.com/api/v3/sami/podcasttts`。

| HTTP 握手头 | 历史客户端使用的值 |
| --- | --- |
| `X-Api-Key` | 独立的豆包播客密钥，客户端读取 `DOUBAO_PODCAST_API_KEY` |
| `X-Api-Resource-Id` | `volc.service_type.10050` |
| `X-Api-Request-Id` | 每次尝试新建 UUID |

这次成功调用没有使用 App ID / Access Token。不能要求用户为了此协议额外配置 `DOUBAO_APP_ID`、`DOUBAO_ACCESS_TOKEN`，也不能假设 Ark 文本 API Key 可通用。

`StartSession` 的 JSON payload 见 `dialogue.json`：

- `action=3`，`nlp_texts` 每项只有真实 voice ID 的 `speaker` 和已核对的 `text`。
- A 为刘飞 `zh_male_liufei_v2_saturn_bigtts`；B 为潇磊 `zh_male_xiaolei_v2_saturn_bigtts`。
- `speaker_info.random_order=false`，`speakers` 为上述固定顺序；头尾音乐关闭，不返回音频 URL。
- `audio_config={"format":"pcm","sample_rate":24000,"speech_rate":0}`。

这是二进制 WebSocket 协议，不能把 JSON 文本直接 `ws.send()` 当作完整实现。使用归档帮助代码的 `Message.marshal/from_bytes` 和连接/会话函数作为线格式参考，再按项目规范实现。

## 已成功的事件顺序

| 阶段 | 客户端发送 | 接收与处理 |
| --- | --- | --- |
| 连接 | `StartConnection=1`，payload `{}` | 等待 `ConnectionStarted=50` |
| 会话 | `StartSession=100`，UTF-8 JSON 和新会话 UUID | 等待 `SessionStarted=150` |
| 提交完毕 | **立刻**发送 `FinishSession=102` | 开始读取逐轮结果 |
| 轮次 | — | `PodcastRoundStart=360`：JSON，逐项核对 `speaker`、`text` 与输入顺序 |
| 音频 | — | `PodcastRoundResponse=361`：当前轮的 PCM 字节，可以多包 |
| 轮结束 | — | `PodcastRoundEnd=362`：JSON，检查 `is_error`；可有 `audio_duration` |
| 用量 | — | `UsageResponse=154`：JSON 中的 `usage`，可插入上述阶段 |
| 会话结束 | — | `SessionFinished=152`；必须没有未结束轮，完成轮数必须等于输入轮数 |
| 断开 | `FinishConnection=2` | 等待 `ConnectionFinished=52` |

历史代码把 `MsgType.Error=15` 映射为安全的数字错误码。连接失败、会话失败、未知事件、畸形帧、文本/音色/轮数不匹配都应受控报错，不能返回部分音频假装成功。
归档不是完整生产状态机；新增实现需要为这些分支补假 WebSocket 测试。

历史超时为建连 30 秒、每次接收 60 秒、整次调用 600 秒。这些是实验护栏，生产版应服从调用方截止时间和取消信号。
演示里的 30 轮、单轮 300 字、合计 1500 字和 300 秒上限也都是本地预算，不是经验证的服务配额。
不自动重连、不重发会话、不重新合成；取消后安全关闭。

## 音频与时间信息

已测试的是 **24 kHz、单声道、16 位 PCM**，客户端以 little-endian PCM 包装 WAV，实际时长按 `字节数 / (24000 × 2)` 得到。
逐轮起止时间可按累计 PCM 字节数推导。这是客户端推导，**没有验证服务器原生绝对时间戳**。
归档客户端对 `audio_duration` 和字节时长做宽容差比对。

没有实测服务端直接输出 MP3 或 WAV。生产接线可先接收同样的 PCM，再在本地封装 WAV；如果需要 MP3，在本地明确转码并把真实格式、模型/协议版本纳入缓存键和快照。
不能只把 PCM 换扩展名，不能用音频包格式不一致的假响应证明已支持真实 MP3。

## 用量与成本

历史安全回执中有两条 `usage`：

```json
[
  {"input_text_tokens": 0, "output_audio_tokens": 403},
  {"input_text_tokens": 0, "output_audio_tokens": 308}
]
```

合计输入文本 token **0**、输出音频 token **711**，音频 **28.491625 秒**，整次耗时约 **17.83 秒**，重试 **0**。
这是一次历史小样本，不能承诺所有节目都符合这个速度或价格。

记录真实的 `input_text_tokens`、`output_audio_tokens`，保留已知的零；不能用正文字符数替代供应商音频 token 计费。
允许缺用量为 `null`，费用未知也为 `null`，不填 0。可以另记发送字符数，但注明它只是本地计数。
这次没有冻结价格证据，不能据此新增价格常量或宣称价格已验证。

部分用量已到、后续断流/取消时保留已知用量并标记不完整；拿到完整回执后，即使校验、转码、上传存储失败也保留已知数值。
每次真实尝试只落一条最终事件，失败状态和已知用量可以同时存在；安全诊断投影/报表不能把新增字段丢掉。
禁止记录完整请求、正文、原始响应/错误体、认证头和签名 URL；数字字段要排除 bool、负数、非有限数值。

## 如何使用此参考

先将协议、配置、账本与 #302 的恢复/失败修复一起离线完成；不必另开一轮广泛架构设计。
把 codec 和调用顺序移入正式适配器，测试通过假 WebSocket 驱动，运行时不从 `docs` 导入。
保留第三方许可与修改声明，避免原样引入归档里的演示目录/文件写入方式。

本目录的参考脚本依赖 `websockets`，不应被 CI 自动运行或安装全局依赖。可用已包含依赖的环境仅执行：

```sh
python call_podcast.py
```

预期 `mode=dry_run`、`network_calls=0`。本次不授权执行 `--live`，不部署，不改生产变量；真实调用留到下一次明确安排的一次最小验收。
