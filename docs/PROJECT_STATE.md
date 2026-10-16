# WaveCast Project State

Updated: 2026-10-16（北京时间）。唯一当前状态入口。旧过程记录已归档，不能把其中“未发布／待试听”等描述当成当前事实。

## 当前任务与暂停点

用户认可“共同编辑方法＋电台默认定位＋本期编辑计划”的方向，下一轮工程只聚焦开场。**方法论与开篇优化尚未实施，没有修改运行代码或生产提示词。** 用户要求先记录讨论，再帮助检查一期真实节目；当前优先等待其节目线索并检查该节目，之后结合反馈恢复开场工作。此次检查对象尚未指定，不要把历史样本当成当前待查节目。

完整设计、已检查代码入口、研究来源、方大同案例与实施验收见 [节目编辑方法与开篇优化](design/programme-editorial-method-and-opening.md)。用户偏好方法论式指导，完整范文保留人类评审，不直接给模型模仿。共享方法适配五台，不维护五套完整提示词；用户具体要求优先于电台默认值。

开场目标：重文本在前两首附近建立具体主题；轻文本自然进入收听，可简短衔接或留白；NONE 保持无主持。短开场与首曲后的开篇分工、不重复。复用已有提案与首个 Writer，优先传递简介、编辑方向、已播开场和确认的歌曲；不等待整套研究、不凭歌名编背景。时长仅有试听候选，未设跨电台硬下限。

本轮暂不改全选曲算法、正文、播放器、模型或响度，不新增模型复审／范文打分／通用 skill 引擎。台标音乐是后续 bonus。后续流程：实现与必要测试 → 一份 PR 到 integration → CI／测试部署 → 用户试听 → 认可后发 main；本次讨论不是下一轮直接生产部署授权。

## 已发布基线

- 正式站：**https://wavecast.space**。#299–#310 经 [#311](https://github.com/ZakuZakuu/wavecast/pull/311) 发布；main 发布提交 `6be49197cce31a5a87afe7f5c1cd4d184babc083`，integration 已同步该提交。当前文档工作分支为 `docs/production-release-20261016`，此前部署记录也只推在该分支，恢复实现时注意从当前集成源码带入必要文档。
- [release CI](https://github.com/ZakuZakuu/wavecast/actions/runs/38898753313)：1660 通过、3 跳过；Web／Docker 冒烟通过。[main CI](https://github.com/ZakuZakuu/wavecast/actions/runs/38907140961) 全绿。
- Railway 正式 API 部署 `b9d58a4c-6ba2-41ff-9d9e-14a760c2c349` SUCCESS，Vercel 正式部署 `dpl_2fzNxTHMXzm4LMUWktEzjgtcimFd` READY；正式域名已核实指向它，API 与 Web 同源 release_check 通过。这是 2026-10-16 发布时的核实结果，后续运维先读实时状态。
- 当前链路：Pro 研究规划／素材、Lite 写稿，豆包单人 TTS 与双人播客，Exa 检索。单人取消常规模型核对、改写和逐句删减；完整前文、来源、日期／人物状态约束和必要代码检查保留。见 [ADR 0031](adr/0031-one-pass-radio-writing.md)。
- 已发布播放器恢复、主持词窗口、旁白时长取整、响度和旧清单兼容、写稿防重复、按节目用量持久化。旧稿和已发布音频不重写；没有新增数据库迁移。上一轮用户确认播放无硬性阻塞，接受文笔剩余问题后发布。

## 部署与排查要点

- Railway 项目 `45d78b7e-2d61-4dc0-b9eb-5788eb1bff84`，环境 `26f5b192-0523-44d8-a1fa-2ee1b8d2eae1` 名为 production，但正式与测试是独立服务／数据库。
- 正式 API 服务 `c6a6389b-634e-4c32-b5dd-34cd5407e1fe`，https://wavecast.up.railway.app ，当前固定在已验收发布 SHA。
- 测试 API 服务 `ac7a2c75-e66f-477e-aeb3-71d029ccc337`，https://integration-test-api-production.up.railway.app ，跟随 integration；测试网页 https://wavecast-web-git-integration-zaku-zakuu.vercel.app 。合并 integration 可能打断测试生成任务。
- Vercel 项目 `prj_WGzuADDs2X85j2KJpfobAvjoOW23`，team `team_lSnGo6eYVVyDSW7rGC1BYyyx`。本次受控发布曾临时关闭自动域名分配；用户随后明确同意，**已恢复 autoAssignCustomDomains=true**。不要沿用“仍待授权恢复”的旧记录。
- 生产的 Ark／播客／普通 TTS 三项密钥通过 Railway 变量引用复用 integration-test-api 的密钥；删除测试服务或改动密钥前先迁移引用。模型 ID 与行为选择器是生产明确值。生产数据库、认证、音乐拓扑和卷保留原配置。
- 生产旧代码未必能读取新节目状态，回退优先向前修复或独立回退 Web，不假定直接重部署旧 API 一定安全。Web 后端地址与预览保护也要按具体部署核实。
- `GET /api/episodes/{id}/usage` 有归属检查，用量按节目持久化、币种分开、未知费用单列。已有节目听回不等于重新生成，不主动为检查启动额外付费验收。
- 历史测试样本 `ba9829b5-62b8-44e4-b1fb-c7cd8f1fcc59`（方大同的情歌慢热，#309 版）约 27 分钟；新写稿测试样本 `e916617c-715f-4b6d-8512-f33647fdb821`（#310 版）。这些仅供历史对照。

## 长期边界与资料入口

- 音乐连续性优先，已播放／已可跳转前缀保持不可变，未来未发布内容可调整。离开播放页继续播放是已实现行为；不等于退出收听会话。
- 程序生成已有角色分工；本轮不做大规模播放器／运行时重构。电台默认表达已有部分配置，不代表完整的五台编辑方法已经实现。
- 调试先按具体节目、稿件、素材和日志建立证据。历史的曲目背景结构化偶发失败、手机后台租约恢复原因不明等，不凭推测扩大修复。
- [AGENTS](../AGENTS.md)、[产品目标](PRELIMINARY_PRODUCT_TARGET.md)、[长期产品与架构合同](CODEX_HANDOFF.md)、[Frost 设计](design/frost/HANDOFF.md)、[部署 runbook](deployment/railway-vercel.md)、[CI](deployment/ci.md)。
- 本次收敛前的完整状态保存在 [历史归档](history/PROJECT_STATE-before-opening-2026-10-16.md)，更早记录也保持；归档不是当前任务清单。
