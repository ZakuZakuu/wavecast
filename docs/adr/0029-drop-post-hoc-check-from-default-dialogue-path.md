# ADR 0029: 默认双人路径不再做事后核对、修复与复核

- 状态：已实现（离线验证；默认双人功能开关 `WAVECAST_DIALOGUE_RADIO` 仍关闭）。**取代** ADR 0025 中的事后 Pro 核对 / 局部修复 / 复核，以及 ADR 0028 的核对定位、修复提示和修复统计。
- 日期：2026-10-15
- 性质：产品取舍。WaveCast 目前是 demo 级的轻量娱乐应用，播客类内容对知识严谨性的要求本来就不高；这条核对链路已在两次真实验收里阻塞进度，且维护成本高。

## 背景（事实，不是辩护）

- 第一次真实验收（2026-10-15，冻结证据）：首检被正则规则拦下两句**有依据**的话，靠一次修复通过（修复整句删掉了第 5 轮的一句，记为信息损失）。
- 第二次真实验收（同日，实时检索）：Pro 核对认为被查的句子有依据，只因 Writer 少列了一个事实 ID，代码判为问题；修复后同样的原因再次触发，最终 `unresolved_after_repair`，没有产出音频。
- 两次里核对都没有抓到一处真正的事实错误。核对相关代码与测试约 4400 行，其中 `fact_support.py` 的正则/词表占大头。

## 决定

默认链路改为：

```text
实时检索 → Pro 素材提炼 → Lite 写稿 → 基础校验 → 豆包配音
```

**移除**（默认路径上）：事后 Pro 核对、局部修复、复核，以及只服务它们的代码——`dialogue_check.py`、`dialogue_metrics.py`（修复统计）、`DialogueRepairer`/`DialogueRepair`/`TurnFix` 与修复提示、`watch_notes`/`locate_quote`/`source_context`、`MaterialFact.source_title/context`、`current_usage_scope`，以及对应测试和夹具。对话栈不再构建 `fact_check` 模型；`fact_check` 角色本身仍属于单人 Writer 路径，不受影响。

**保留**：

- 素材提炼时的证据存在、引文来自对应来源、曲目/版本范围约束（`verify_material`，含其中用到的 `fact_support` 函数）。
- Writer 引用的事实 ID 必须属于本份素材；故事用途至少引用一条；对话结构（说话人、`tts_text` 不由模型提供）和各电台的时长硬上限。
- 用量记录、取消、缓存、恢复（预约账本、存档、音频快照）。
- 单人路径与 `fact_support.FactChecker`。

语义（归属、限定词、转述是否忠实）主要由素材质量和写稿提示约束，接受 demo 阶段的小偏差。**不**新增严格模式、风险分类器、抽查开关、自动删句或替代修复流程。

## 存档与兼容

- 现在产出的片段 `status="ready"`、`model_checked=false`、`repaired_turns=[]`、`first_check_issues=[]`、`calls_used=1`：如实记录“只经代码校验，没有模型核对”，不伪记 `model_checked=true`。
- 记录格式（`schema_version=1`）不变。更早保存的记录（`status="repaired"`、`model_checked=true`、带首检问题）仍可读取、恢复，按各自真实状态呈现；`DialogueStatus.REPAIRED` 只为它们保留。保存与恢复不重复调用模型或配音。
- 历史实验结果（`tests/fixtures/dialogue_portrait_20261015/` 与 ADR 0028 的结论）保持原样；`tests/test_dialogue_archive.py` 只检查它未被改动、不含凭据。
- 只含 `source_title`/`context` 的素材 JSON 是 #303 合入后到本次之间、仅在探针产物里出现过的格式（该字段只在默认关闭的功能里写入）；读取这类 JSON 需要先去掉这两个键。

## 代价与未覆盖

- 少数越界措辞（例如素材没说过的“一直”“更成熟”）会直接进入节目；不会再被拦或改写。
- 这条路径只证明“结构合法的稿子可以不经核对配音”；稿子的语言质量、素材覆盖和时长（目标上限偶尔会略超，仍以硬上限为准）仍由真实试听评判。
- 一次配音是否成功、音频时长与估算的偏差，见当次验收报告，不在本文结论里。
