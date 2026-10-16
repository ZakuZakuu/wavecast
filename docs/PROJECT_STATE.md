# WaveCast Project State

Updated: 2026-10-17（北京时间）。唯一当前状态入口。旧过程记录已归档，不能把其中“未发布／待试听”等描述当成当前事实。

## 当前任务与暂停点

用户睡前授权的外文口播/空稿修复已通过 [#312](https://github.com/ZakuZakuu/wavecast/pull/312) 合入 integration，并完成测试部署；**代码没有发布 main**。当前工作分支为 `docs/opening-implementation-plan-20261017`，追加的开场研究与最新交接记录单独保存在该文档分支，未触发额外测试部署。下轮从 integration 新建实现分支时带入这些文档更新。

排查对象为正式节目《椎名林檎的两套呼吸》（`701677ba-5d95-4e59-94d6-c3b3b208ba92`）：约28分29秒，仅4次单人TTS、合计47秒；素材整理反复TypeError、五章零要点，唯一约82秒双人稿因日文假名被整段跳过。已用保存稿件离线复现，也复现了空GeneratedChapter异常；实际两处ValidationError没有堆栈。

正式/测试API都曾缺少独立的曲目素材整理provider变量。Ark Writer＋全局mock会让该角色绑定不支持brief schema的mock，已离线复现相同TypeError；Railway OAuth不返回变量值，所以实际生产全局模式未直接核实。用户授权后，正式API与测试API均显式设置 `WAVECAST_TRACK_RESEARCH_PROVIDER=deepseek`；测试变量随#312同一次部署生效，未另外重启。

#312保留语音能力检查：单人/双人共用名称指导；双人把已知歌曲转成可读口播，原文/事实引用不改；无法处理的外文在存稿前拒绝，由已有单人回退接手。只省略明确“原名”注释，不删其他括号说明或逐句裁剪，不增翻译/复审调用；空叙述章节返回无旁白。离线测试与完整CI均通过，尚未主动生成付费验收节目或真机试听。旧音频不回填，明早需新建节目验证。

**原定方法论与开篇优化尚未实施。** 研究、代码入口与实施取舍已补在 [节目编辑方法与开篇优化第8节](design/programme-editorial-method-and-opening.md#8-2026-10-17进一步代码研究明早实施前的建议)。下一轮可直接从“启用提案短开场＋为首个A→B Writer补编辑背景/已播开场/明确开篇任务”入手。优先一份共享方法、五台短定位、每期已有简介，完整方大同范文只用于人类评审，不直接喂模型。开篇应替代冲突的普通串场move/口吻样例/字数下限，而不是再堆一层模板；不把提案意图当证据或承诺未确认歌曲。

重文本在前两首附近建立具体方向；轻文本可简短连接或留白，NONE无主持。不等整套研究、不新建摘要/翻译/复审/选曲调用、不改整套worker/播放器/混音。现有短开场无合适窗口也可能第6秒叠播，不能简单加长后承诺避开主唱。台标音乐仅后续bonus。开场实现 → 集中PR/CI → integration试听 → 用户认可后再发main；睡前授权仅覆盖本轮修复进测试与继续研究。

## 已发布基线

- 正式站：**https://wavecast.space**。#299–#310 经 [#311](https://github.com/ZakuZakuu/wavecast/pull/311) 发布；main 发布提交 `6be49197cce31a5a87afe7f5c1cd4d184babc083`；integration已在此基础上合入#312。此前发布记录与方法论备忘已随#312带入integration；最新开场研究与验收记录在当前文档分支。
- [release CI](https://github.com/ZakuZakuu/wavecast/actions/runs/38898753313)：1660 通过、3 跳过；Web／Docker 冒烟通过。[main CI](https://github.com/ZakuZakuu/wavecast/actions/runs/38907140961) 全绿。
- Railway 正式 API 部署 `b9d58a4c-6ba2-41ff-9d9e-14a760c2c349` SUCCESS，Vercel 正式部署 `dpl_2fzNxTHMXzm4LMUWktEzjgtcimFd` READY；正式域名已核实指向它，API 与 Web 同源 release_check 通过。这是 2026-10-16 发布时的核实结果，后续运维先读实时状态。
- 2026-10-17北京时间约00:50，用户授权修正正式API变量`WAVECAST_TRACK_RESEARCH_PROVIDER=deepseek`；新API部署`a9910361-5488-4483-9459-17cc89082f73`已观测SUCCESS，启动和健康检查200。该次只改正式API配置，源码仍固定在上述main发布SHA；随后测试服务的变化见下。新变量名称已回读确认；OAuth不提供变量值读回，写入工具确认设置成功。新节目素材整理的付费调用尚未验收，不能据部署成功断言整期生成质量已恢复。
- 测试检查点：#312合并提交 `bcc63b0bbab3f54e9fd8cddcae093e762276a10e`；[CI](https://github.com/ZakuZakuu/wavecast/actions/runs/38939390379)基于最终head `c689fa4` 全绿。Railway测试API部署 `9f05e0c4-da60-48f6-a07b-dc445d8b1589` SUCCESS，Vercel预览 `dpl_Fw3hH8bBCZz8EvUxFrPbkJtKLJKo` READY，二者SHA一致；API冒烟、经Vercel官方认证的网页/同源API检查均通过。预览地址仍为下方integration链接，Deployment Protection保持开启。
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
