# 最小真实链路验收准备（2026-10-15）

基于 integration 合并提交 `b53edd564cfd4cba25bfe0de1599ebaf2e6c6cf9`。
本目录当前状态：**仅离线预检通过，真实调用 0 次**，等待重新临时注入已获授权的两个 key。

范围固定为素材 Pro → 双人写稿 Lite → 核对 Pro → B 音色语速 0 → 本地 WAV / HLS。
最多 3 次文本、1 次配音；每步一次，失败即停，不修复重抽、不走单人 Writer 兜底。
语音最多 70 秒；豆包费用仍未冻结价格，只记录实际音频 token 与未知费用。
这是一小段口播的服务接线验收，不是完整音乐电台或生产部署验收。

`evidence.frozen.json` 是历史 2026-10-14 Exa C 检索的三份证据投影，保留出处、摘录和 query。
来源为当时冻结的 `auto-research-experiment-20261014/new-search/C-frozen-input.json`，
筛选 Hitoradio 专访、网易专访和 QQ 音乐专辑记录；不新增检索，不使用测试里重建的事实冒充真实检索。
摘录按现有 Evidence 契约裁到 2000 字符。实际可支持多少事实由素材服务和核对者决定，不能预先视为全数支持。

默认预检（不联网、不要求 key）：

```sh
PYTHONPATH=backend:. uv run python scripts/live_dialogue_probe.py \
  --evidence docs/research/dialogue-radio-2026-10/live-acceptance-20261015/evidence.frozen.json \
  --run-dir .wavecast-data/dialogue-live-20261015
```

加 `--offline` 可用明确标注的重建夹具和假音频走到真实本地 HLS renderer；与正式冻结输入不同。
本次 offline 已成功：2 轮假稿、3 秒假音频、1 个真实 HLS 分片，重复 render 的 manifest 相同，付费调用 0。
三个供应商 strict schema 的本地规整均通过，尚未证明真实 API 会接受。

正式运行需要 `--live --prompt-keys`（隐藏输入），或临时环境变量
`ARK_API_KEY` / `DOUBAO_PODCAST_API_KEY`。原临时输入不保存在代码或报告中。
attempt.json 以独占方式创建，中断或失败后不能静默重跑同一目录。
只输出/保存安全用量和阶段状态；已核对稿件作为节目产物保存，不保存原始模型请求/响应。

不部署、不改变 main、integration 或生产变量。正式报告和可试听音频待真实调用后补。
