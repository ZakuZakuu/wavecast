# 豆包单人 TTS（刘飞 2.0）

单人开场、串场和结尾可以改用豆包的普通语音合成，双人对话继续用原来的播客模型。两者各管一段，不互相替代。

## 打开方式

```text
WAVECAST_TTS_PROVIDER=doubao        # 默认 inherit（实时模式用 MiniMax）；minimax 仍可显式选择
DOUBAO_TTS_API_KEY=...              # 单人 TTS 自己的 key，不是播客的，也不是 Ark 文本 key；不需要 MiniMax key
DOUBAO_TTS_VOICE_ID=zh_male_liufei_uranus_bigtts   # 默认值
```

部署变量不在这个 PR 里改；等 integration 网页验收时再统一切换。

## 已验证的调用（2026-10-16，一次真实调用，由 GPT 完成）

`POST https://openspeech.bytedance.com/api/v3/tts/unidirectional`，`X-Api-Key`、`X-Api-Resource-Id: seed-tts-2.0`，PCM、24000 Hz、`speech_rate=0`，请求头 `X-Control-Require-Usage-Tokens-Return: *` 让回执带 `usage.text_words`。回复是一串 JSON 块：`code=0` 带 base64 音频，最后 `code=20000000` 结束。81 字符、13.78 秒音频、耗时 9.6 秒，计费 81 字符，约 ¥0.0243。音色接近但表达弱于播客版。

适配器（`providers/doubao_tts.py`）只支持上面这条路径：

- **请求 ID：** 每次真实请求带一个新的随机 UUID（`X-Api-Request-Id`，文档要求；缓存命中不发请求也没有 ID），同一个 ID 写进用量事件的 `request_id`。
- **完成判定：** HTTP 200 不算完成；必须收到结束码 20000000，否则报错、不入库。回复边收边读：服务已报告的计费字符数（含明确的 0）在回复中途出错、断流、超时或被取消时仍写进那条最终事件；一直没收到才是未知。
- **存储：** 本地把 PCM 封成 WAV（与双人对话一致），不复用 MiniMax 的 MP3。
- **语速：** 项目里的 `SpeechProfile.speed` 是倍速（1.0 正常）；豆包的 `speech_rate` 0 为正常，`(speed − 1) × 100`，限制在 −50…100。转换只在适配器里。适配器的基准倍速是 1.0。
- **缓存：** key 含供应商、模型、音色、豆包语速、音频参数和文本，不会命中 MiniMax 的音频；命中不再请求。
- **文本：** 去掉 MiniMax 的 `(breath)` 提示记号（这个音色会把它念出来）；cue 仍留在缓存 key 里。
- **用量：** 成功、失败、取消各一条最终事件；按回执的计费字符数、¥3 / 万字符估价；回执缺失记未知（None），明确返回的 0 保留；缓存命中记已知的 0。
- **不重试、不自动改用 MiniMax。**

## 未验证

- 请求体布局按供应商文档的 v3 结构写（`user` + `req_params{text, speaker, audio_params}`）；本批没有新增任何真实调用，需要对照 GPT 的验证脚本核一遍字段名。
- 响度：MiniMax 用 `vol=1.7` 对到约 −20 LUFS；豆包输出的响度还没量，可能比音乐轻或重，等试听再调。
- 第一版用默认语气，没有语气指令。
