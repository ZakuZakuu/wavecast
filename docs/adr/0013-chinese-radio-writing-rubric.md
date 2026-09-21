# ADR 0013: Language-scoped Chinese radio-writing rubric

- Status: Accepted
- Date: 2026-09-21

## Context

Phase 5.2 的首次试听显示，选曲和 editorial arc 基本成立，但部分旁白偏向文章腔、泛化文化判断和模板式收尾。现有 Writer 约束只有通用的 warm, concise, spoken 与 natural, specific, speakable，不足以支持稳定的人审。

## Decision

先在 Phase 5.3A 建立一个只适用于 zh-CN 的 typed human-review rubric，并配套 credential-free、自造正反例。rubric 复用现有质量评估边界，但把中文音乐广播需要的人审问题具体化为：

- concrete before abstract；
- listen-for cue；
- fact → sound → connection；
- one spoken beat；
- speakable Chinese；
- grounded interpretation；
- contextual deixis；
- cultural precision；
- outro callback；
- no forced cleverness。

本阶段只增加评估契约、语料来源笔记和 fixtures/tests，不增加 RadioScriptBlock 字段，不改变 NarrationSlotContext、EpisodeAssembly 或播放架构，也不做 regex 文本后处理。下一阶段再根据 rubric 决定最小的 zh-CN Writer prompt guidance 改动。

## Corpus boundary

只保留公开来源链接、抽象观察和自造例句；不把完整逐字稿、长段落或主持人特有措辞写入仓库或 prompt。语料来源与观察记录见 docs/research/phase53-radio-writing-corpus.md。

## Consequences

- 人审有稳定、可复用的中文音乐广播问题，而不是自动替文风打分。
- fixture 可以在无凭据、无 provider 调用的情况下测试 rubric 完整性和语言边界。
- Writer 运行时暂时不变，避免在 rubric 尚未验证前引入过早的 prompt 或后处理耦合。
- 未来 Writer prompt 应只读取语言匹配的指导，不把中文规则污染到 en-US 或 ja-JP。
