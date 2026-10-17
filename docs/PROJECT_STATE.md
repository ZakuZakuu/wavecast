# WaveCast Project State

Updated: 2026-10-18（北京时间）。唯一当前状态入口。旧过程记录已归档，不能把其中“未发布／待试听”等描述当成当前事实。

## 当前任务

用户已完成#316版人物志试听并明确授权发布；[#318](https://github.com/ZakuZakuu/wavecast/pull/318)已合入main `485ea1252c070d090b57cf6bc3e1cc7814ca3d2f`，integration已快进到同SHA。应用代码与已试听测试版`e85241c`一致，发布分支只补状态文档，本轮没有实现额外修复。正式站 **https://wavecast.space** 已通过只读检查。

已发布内容：可说外文/中文歌名、完整开篇/收尾、重文本台正文讨论和素材编辑方向传递。设计见[ADR 0032](adr/0032-editorial-opening.md)至[0035](adr/0035-substantive-opening-and-closing.md)；无新增模型复审或摘要流水线，旧节目不补稿。

正式API部署`a96c34f9-82be-469d-93bf-c6ea2b37bffe` SUCCESS，源码固定为`485ea12`；启动日志无ERROR/Traceback。前端构建输入相对旧正式版没有变化，Vercel按ignore规则保留原READY构建`dpl_2fzNxTHMXzm4LMUWktEzjgtcimFd`（Web SHA `6be4919`），无需与API SHA强行相同。正式API和wavecast.space同源health/公开节目/未知404、节目页面OG标题及未知短链均通过。没有改模型、密钥、数据库或新增付费节目。

[#318发布CI](https://github.com/ZakuZakuu/wavecast/actions/runs/39055489756)全绿：后端1741通过/3跳过、Web299通过、Ruff/Mypy/Docker冒烟通过；合并后的完整文件树与该PR head一致。main自动复跑见[39056788684](https://github.com/ZakuZakuu/wavecast/actions/runs/39056788684)，不把尚未观察到的结果写成通过。#316原完整CI同样通过，试听测试部署原为`e85241c`；integration快进后服务继续跟随同一已发布应用代码。

已知后续事项：和弦符号/乐理缩写的TTS读法（dim被拆成字母）记入[#317](https://github.com/ZakuZakuu/wavecast/issues/317)，优先由Writer口语化，准确保留音乐含义，不新增翻译/复审。此前Lite连续429由免费额度耗尽自动停用造成，用户已关闭；最新线上Lite成功，授权的临时key最小调用也200（212 token），未写仓库或更换部署密钥。渐进任务心跳失活取消后resume未观察到继续生成已记入[#319](https://github.com/ZakuZakuu/wavecast/issues/319)，根因待查；偶发编排/素材格式问题也留待后续。用户再次明确本轮只记issue并发布，不继续修复或重构租约。

**下一步只讨论UI，尚未授权实现。** 用户次日与Claude合作，本轮只读调研已记在[研究记录](design/ui-next-round-research-2026-10-18.md)和[35项辅助文案清单](design/ui-microcopy-inventory-2026-10-18.md)。[#320](https://github.com/ZakuZakuu/wavecast/issues/320)歌曲封面（网易云实测有图，需透传）；既有[#204](https://github.com/ZakuZakuu/wavecast/issues/204)已更新为快捷整期生成/调频后台生成及可选提醒；[#321](https://github.com/ZakuZakuu/wavecast/issues/321)跳转保留曲前口播/路线显示旁白；[#322](https://github.com/ZakuZakuu/wavecast/issues/322)小字仅盘点、不决定删改；[#323](https://github.com/ZakuZakuu/wavecast/issues/323)封面多版设计。未修改应用、开修复PR或新增付费节目。开场方法论仍见[原设计](design/programme-editorial-method-and-opening.md)，台标音乐留后续。

## 已发布基线

- 当前正式为上述#318发布提交，含#312–#316；上一正式发布为#311 `6be4919`。旧CI和配置部署只作历史，不再代表当前API版本。
- 生产API继续使用明确的`WAVECAST_TRACK_RESEARCH_PROVIDER=deepseek`；Ark研究规划/素材/写稿角色及豆包语音配置保持，OAuth只读回变量名。此前模型额度问题由用户在方舟侧恢复，已观察到线上写稿成功，不把健康检查等同整期付费生成验收。
- 中文口播名见[ADR 0034](adr/0034-grounded-spoken-song-titles.md)。#315和#316的测试检查、用户试听已完成；当前无需再发布同一批功能。

- 当前链路：Pro 研究规划／素材、Lite 写稿，豆包单人 TTS 与双人播客，Exa 检索。单人取消常规模型核对、改写和逐句删减；完整前文、来源、日期／人物状态约束和必要代码检查保留。见 [ADR 0031](adr/0031-one-pass-radio-writing.md)。
- 已发布播放器恢复、主持词窗口、旁白时长取整、响度和旧清单兼容、写稿防重复、按节目用量持久化。旧稿和已发布音频不重写；没有新增数据库迁移。上一轮用户确认播放无硬性阻塞，接受文笔剩余问题后发布。

## 部署与排查要点

- Railway 项目 `45d78b7e-2d61-4dc0-b9eb-5788eb1bff84`，环境 `26f5b192-0523-44d8-a1fa-2ee1b8d2eae1` 名为 production，但正式与测试是独立服务／数据库。
- 正式 API 服务 `c6a6389b-634e-4c32-b5dd-34cd5407e1fe`，https://wavecast.up.railway.app ，当前固定在已验收发布 SHA。
- 测试 API 服务 `ac7a2c75-e66f-477e-aeb3-71d029ccc337`，https://integration-test-api-production.up.railway.app ，跟随 integration；测试网页 https://wavecast-web-git-integration-zaku-zakuu.vercel.app 。合并 integration 可能打断测试生成任务。
- 用户授权将测试 API 的 `WAVECAST_GUEST_PROGRAM_LIMIT` 从5调至50（同一访客累计创建额度），已重部署成功并通过只读API冒烟。正式服务与全站日额度未改；OAuth只读回变量名，写入工具已确认设置。
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
