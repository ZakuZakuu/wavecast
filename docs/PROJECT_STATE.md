# WaveCast Project State

Updated: 2026-10-17（北京时间）。唯一当前状态入口。旧过程记录已归档，不能把其中“未发布／待试听”等描述当成当前事实。

## 当前任务

开场优化已通过 [#313](https://github.com/ZakuZakuu/wavecast/pull/313) 合入 integration（`815f0a0`），CI全绿，测试API/网页部署与只读冒烟均通过。main仍是`6be4919`，#312外文口播修复和#313开场均未发布正式环境。当前分支 `docs/opening-test-checkpoint-20261017` 仅保存验收交接，不为状态文档再触发部署；下一轮从integration开发时带入此文档更新。

旧案《椎名林檎的两套呼吸》（`701677ba-5d95-4e59-94d6-c3b3b208ba92`）约28分29秒，仅47秒单人口播；素材整理反复TypeError，唯一双人稿因日文假名整段跳过，均已离线复现。旧音频不回填，应新建节目验证修复。

正式/测试API都曾缺少独立的曲目素材整理provider变量。Ark Writer＋全局mock会让该角色绑定不支持brief schema的mock，已离线复现相同TypeError；Railway OAuth不返回变量值，所以实际生产全局模式未直接核实。用户授权后，正式API与测试API均显式设置 `WAVECAST_TRACK_RESEARCH_PROVIDER=deepseek`；测试变量随#312同一次部署生效，未另外重启。

#312保留语音检查，单人/双人共用名称指导；双人确定性转换可读名称、保留原文与引用，无法处理的外文在存稿前拒绝并由单人回退。只省略明确“原名”注释，不裁其他括号说明、不加翻译/复审；空叙述章节返回无旁白。实现已在 integration，尚未主动付费生成或真机验收。

**开篇实现与代码验证完成，待新节目试听。** 见 [ADR 0032](adr/0032-editorial-opening.md)：中文采用提案本期导入＋短台呼，缺失/超长/不可读仍用完整旧兜底；分享复用可选导入字段。LiveEpisode保存已有简介，首个A→B Writer收到需求、编辑意图、可播开场原文和确认曲目，用开篇任务替代普通move/口吻样例/字数下限。FULL/LIGHT目标30/12秒，NONE不写，槽位仍是before-track。方法共享，五台各一句默认，不喂完整范文、不增加模型调用，事实/日期/配音检查和正文不改。

下一步：重新提交选题生成新提案/节目，试听一份人物志重文本、一份轻文本。听前两首是否建立具体方向、两处开场是否重复、短开场是否压主唱；旧卡片/旧稿不会自动更新。短导入含台呼估时上限12秒，既有混音无合适窗口可能第6秒叠播。不开新研究/摘要/翻译/复审/选曲调用，不改worker/播放器/混音；台标音乐留后续。用户认可试听后再发布main，本轮尚未获得这次生产发布授权。

## 已发布基线

- 正式站：**https://wavecast.space**。#299–#310 经 [#311](https://github.com/ZakuZakuu/wavecast/pull/311) 发布；main 发布提交 `6be49197cce31a5a87afe7f5c1cd4d184babc083`；integration已在此基础上合入#312、#313。最新验收记录在当前文档分支。
- [release CI](https://github.com/ZakuZakuu/wavecast/actions/runs/38898753313)：1660 通过、3 跳过；Web／Docker 冒烟通过。[main CI](https://github.com/ZakuZakuu/wavecast/actions/runs/38907140961) 全绿。
- Vercel正式部署仍为`dpl_2fzNxTHMXzm4LMUWktEzjgtcimFd`；正式API随后仅做配置重部署，见下。
- 2026-10-17北京时间约00:50，用户授权修正正式API变量`WAVECAST_TRACK_RESEARCH_PROVIDER=deepseek`；新API部署`a9910361-5488-4483-9459-17cc89082f73`已观测SUCCESS，启动和健康检查200。该次只改正式API配置，源码仍固定在上述main发布SHA；随后测试服务的变化见下。新变量名称已回读确认；OAuth不提供变量值读回，写入工具确认设置成功。新节目素材整理的付费调用尚未验收，不能据部署成功断言整期生成质量已恢复。
- 测试检查点：#313合并提交`815f0a04f5c8b4cc46e9998a1d642ae9ba3a4c1b`；[最终CI](https://github.com/ZakuZakuu/wavecast/actions/runs/38998381734)基于head `77e4047`全绿，后端1678通过、3跳过，Web及Docker启动/重启/持久化冒烟通过。首次CI漏改旧测试导入，已修正。Railway测试部署`abfb5fa0-5d61-4a37-a9c9-9496e095c842` SUCCESS、Vercel预览`dpl_66DdHwrcPdj55FtHD3nUSR8ti3z4` READY，SHA一致。API health/公开节目/未知路由、经官方认证的预览网页和同源API均通过；Deployment Protection保持开启，未生成付费节目或真机试听。
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
