# WaveCast Project State

Updated: 2026-10-17（北京时间）。唯一当前状态入口。旧过程记录已归档，不能把其中“未发布／待试听”等描述当成当前事实。

## 当前任务

[#316](https://github.com/ZakuZakuu/wavecast/pull/316)已按用户授权合入测试，integration `e85241c8722224aac4657f5aed51209e582d3f59`，正式/main仍为`6be4919`。包含#315中文口播名、完整开篇/收尾及素材角度修补；设计见[ADR 0035](adr/0035-substantive-opening-and-closing.md)。前两首独立开篇60–90秒、结尾30–45秒；编辑方向/章节任务进入曲目要点、背景和双人素材选择。Curator优先主题贴合，Writer不能用风格词强接普通作品介绍；无额外模型、搜索或复审调用。

最新head `5bb7c20`的[完整CI](https://github.com/ZakuZakuu/wavecast/actions/runs/39050660723)全绿：后端1741通过/3跳过、Web299通过，Ruff/Mypy/Docker冒烟通过；本地相关回归366通过。Railway测试部署`65311344-0c35-4ada-b39f-d0bc53f166e0` SUCCESS、Vercel `dpl_92tqQFq6J8zfpfH1iVyXTWaS958s` READY，两端同合并SHA。API健康/公开读/未知404、受保护预览同源health/公开读/节目页面均通过；正式API/Web部署与SHA已回读确认未变。未启动额外付费节目。

下一步由用户新建节目试听：前两个音乐间隙的完整导入、正文贴合主题、结尾回应本期。自动检查不是文笔验收，旧节目稿/音频不变。当前最新已听样本`b3acf873-35f5-4082-81ad-de34bb860ccd`仍是#315（28:02、两段双人），未验收#316；素材集中在精选/传播信息，缺爵士编配依据。此前认可的#314样本`db15f6cb-2e47-434c-b387-096ddd4f33b1`为31:37、三段双人，TTS估价¥0.565（非实付）；本轮不以demo成本限制口播。

**本轮实现**见[ADR 0033](adr/0033-hosted-programme-delivery.md)：FULL等待在途Writer/TTS及保存，快速开篇共用防重；人物志/来龙去脉FULL主持新节目按时长安排讨论，约30分钟计划3段/交付最低2段、60分钟5/4，按音乐时间分散，预留口播时间。只计实际配音进入时间线、双方参与且有事实支持的讨论；非讨论缝隙可纯音乐。主要段落结束后最多尝试一个未发布补位；不足时返回hosting_coverage短缺并正常保留可播音乐。轻文本台/旧session沿用原策略。开篇复用已有FastStart证据，失败由下一段接过导入任务；提案方向传给Curator，章节任务传给双人Writer。窄切口首曲按精确候选顺序找，不任取同艺人歌曲兜底。无新复审/翻译/摘要调用，不修改已发布前缀。

开场方法论保存在[设计文档](design/programme-editorial-method-and-opening.md)，台标音乐仍留后续。新一轮需新建节目验收完整开篇、三段正文与实际收束；旧节目不补稿。

## 已发布基线

- 正式站：**https://wavecast.space**。#299–#310 经 [#311](https://github.com/ZakuZakuu/wavecast/pull/311) 发布；main 发布提交 `6be49197cce31a5a87afe7f5c1cd4d184babc083`；integration已在此基础上合入#312至#316。
- [release CI](https://github.com/ZakuZakuu/wavecast/actions/runs/38898753313)：1660 通过、3 跳过；Web／Docker 冒烟通过。[main CI](https://github.com/ZakuZakuu/wavecast/actions/runs/38907140961) 全绿。
- Vercel正式部署仍为`dpl_2fzNxTHMXzm4LMUWktEzjgtcimFd`；正式API随后仅做配置重部署，见下。
- 2026-10-17北京时间约00:50，用户授权修正正式API变量`WAVECAST_TRACK_RESEARCH_PROVIDER=deepseek`；新API部署`a9910361-5488-4483-9459-17cc89082f73`已观测SUCCESS，启动和健康检查200。该次只改正式API配置，源码仍固定在上述main发布SHA；随后测试服务的变化见下。新变量名称已回读确认；OAuth不提供变量值读回，写入工具确认设置成功。新节目素材整理的付费调用尚未验收，不能据部署成功断言整期生成质量已恢复。
- 最新测试检查点为上面的#316；#315中文歌名沿素材、持久化、单双人写稿复用，见[ADR 0034](adr/0034-grounded-spoken-song-titles.md)。#314的[完整CI](https://github.com/ZakuZakuu/wavecast/actions/runs/39013104444)1709通过/3跳过；#315的[完整CI](https://github.com/ZakuZakuu/wavecast/actions/runs/39018855425)后端/Web/Docker均通过。预览保护保留；未启动额外付费节目，正式API与main未变。


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
