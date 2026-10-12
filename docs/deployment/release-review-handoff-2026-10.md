# 发布前审查交接（2026-10-12）

给做发布前审查的人（GPT）。审查对象是 `origin/main..origin/integration`：52 个 PR 合并、172 个文件、约 +21,700 行。先读 [release-readiness-2026-10.md](release-readiness-2026-10.md)（范围、迁移、配置、发布顺序）和 [PROJECT_STATE.md](../PROJECT_STATE.md)（每一批改动的来龙去脉和已知限制），再看代码。

用户已决定**整条发布**，合并到 `main` 之前要这次审查通过。请把结论分成：**发布阻塞**、**发布前应修**、**发布后再改**，每条给出文件和行、能复现的输入、建议的修法。没有发现就明确写“没有”，不要凑数。

## 第一轮审查（GPT，针对 `integration@96cebef`）与处理

| # | 发现 | 处理 |
|---|---|---|
| 1 | 阻塞：分享副本的 `topic` 还是分享者原话 | 副本改为逐字段构造：`topic` 变成“标题。简介”，开场白重新生成（去掉“来自你点的…”），新增字段必须在测试里表态是照搬还是重做 |
| 2 | 推荐每日上限靠“一秒内算一批”推断，且锁不跨请求 | 想法带批次 id，按生成次数计数（没有 id 的旧想法仍按时间归并）；每个听众一把进程内共享的锁，在锁内读历史并检查上限；新增快速连换和并发测试（修复前失败） |
| 3 | 分享副本的本地缓存不分账号 | 缓存按身份（账号或游客）保存，用之前向服务器确认归属，404 就清掉并重新领一份；游客登录后其副本作为候选一并校验 |
| 4 | “重新部署旧 API 即可回退”不成立 | 发布文档改为向前修复加开关降级加 Web 回退，写明 API 回退的代价；补了受控的发布顺序和只读的发布检查脚本 `scripts/release_check.py` |
| 发布后 | 短链接接口没有限流 | 接受，发布后再补限流或加长随机码 |

注：第 1 条的初版修复（#280）审查时还没合并，所以审查当时仍然成立。

## 怎么跑

```text
git diff --stat origin/main origin/integration
.venv/bin/ruff check .
.venv/bin/python -m pytest tests -q            # 后端；Postgres 集成测试需要 WAVECAST_TEST_DATABASE_URL（postgresql+asyncpg://…，先 alembic upgrade head）
cd apps/web && npx tsc --noEmit && npx eslint . && npx vitest run
```

CI 在 integration 上每个 PR 都是全绿（后端约 16 分钟）。Web 侧的本地截图脚本不在仓库里，页面效果以 Vercel 预览为准，但**预览读的是旧的生产后端，新接口在预览里不存在**，功能验收只能看代码和测试。

## 重点审查面

### A. 新增的匿名可访问接口（最该仔细看）
- `GET /api/programs/{id}/public`：任何人凭 id 读标题、简介、路线、标签、开场曲目；不返回 `topic`（听众自己输入的请求）。id 是 `proposal-` 加 32 位随机十六进制。
- `GET /api/programs/by-code/{code}`：用 id 的前 10 位十六进制（40 位）换完整 id；匹配多个或没有都返回 404。**问：没有限速时，枚举 40 位空间是否可接受？**（库里有 N 个节目时，随机猜一次命中概率约 N/2⁴⁰。）
- `POST /api/programs/{id}/adopt`：给调用者复制一份分享来的节目，占一个额度，不调用模型。**已修一处**：副本的 `topic` 原先照抄分享者输入的原话，访客能读回，现在改为“标题。简介”（见 `test_the_visitors_copy_does_not_carry_the_sharers_own_words`）。请继续找别的泄露：副本里还有哪些字段来自分享者？（`required_artists`、`anchor_artists`、`presentation_intent`、开场曲目引用。）
- `/p/[code]` 与 `/program/[id]/opengraph-image`：服务器端用内部地址读后端、`revalidate` 300 秒；预览图会从 Google Fonts 现取中文字体。
- 额度：访客点播放才占额度；已拥有的节目不重复占；同一浏览器重复打开同一链接复用上一份副本（`wavecast-adopted-v1`，只在本地）。

### B. 迁移与数据
- 只有 `alembic/versions/0008_avoid_artists.py`：给 `user_preferences` 加 `avoid_artists JSONB NOT NULL DEFAULT '[]'`。确认和 `0005`–`0007`（已在 main 上）衔接、升降级都可跑。
- `PUT /api/user-preferences/me`（新手引导保存）必须保留已有的 `avoid_artists`；`DELETE` 会连它一起清掉（预期）。
- `POST …/avoid-artists` 与 `…/remove`：新增或取消一位艺人，最新在前、去重、最多 20 个。

### C. 额度、成本、并发
- 首页推荐：`RecommendationService`（每次展示 4 档、`换一批` 先轮换库存、每人每天真实生成最多 4 次、每个用户一把锁）。看有没有死锁（历史曾在内存仓库里踩过：生成闭包里读库）、跨用户串数据、上限绕过。
- 提案、改写、事实核对的用量记录（`providers/usage.py`）：缓存命中和未命中的统计，未知不等于零。
- 全站每日上限、游客和登录用户的上限在 `services/api/main.py` 顶部。

### D. 推荐与“少放”
- 想法生成：`avoid_artists` 进提示词，模型仍写进去的想法在 `_without_avoided_artists` 里剔掉（剔完不足三个就保留原样）。
- 提案生成：`taste_context` 里带“少放：…”，提示词说明其含义。
- 标题：`title_style.py`（`TITLE_GUIDANCE`、`cover_title` 兜底、冒号标题重试仅用于想法批次）；草稿结构里 `title` 和 `cover_title` 排在最后，提案提示词带电台信息。

### E. 生成链路（第一次进生产，量最大）
按 PROJECT_STATE 的顺序读：事实核对（`intelligence/fact_support.py`、`writer.py` 的改写和 `with_carried_risks`）、按曲目找资料（`WAVECAST_TRACK_RESEARCH`，可关）、版本和范围约束（`route_work.py`、`assembly.py`）、选曲候选池（`WAVECAST_CATALOG_POOL`）、时长分级（`WAVECAST_DURATION_SCALING`）、声音和主持词、音乐网关。**事实核对没有开关。**
文本质量没有验收；已知限制写在 `PROJECT_STATE.md` 和 `research/text-acceptance-2026-10/`（检查器一致性、“非事实”分类偏宽、素材单薄时内容单薄）。请重点看：会不会在生产里把真实用户的节目搞坏（异常处理、超时、重试、半成品状态、费用失控），而不是文风。

### F. Web
- `/program/[id]`（`components/programme/programme-detail-page.tsx`）：按钮状态（播放 / 继续播放 / 再听一次 / 回到播放页）来自本地节目库记录和正在播放的节目；“再听一次”会把本地检查点和服务端检查点清零。
- 播放页“更多”里的节目详情和分享：先关底部面板，再 320ms 后跳转或开分享面板，是为了避开面板自己关闭时的历史回退（`lib/overlay-stack.ts`）。看是否稳妥。
- 节目库整行改成进详情，环形按钮才直接续播；`/program` 不显示底部导航和迷你播放器（`lib/chrome-visibility.ts`）。
- 首页：卡片先弹详情面板，点播放才生成；游客精选卡片显示 `displayTitle`，发给接口的仍是 `prompt`。
- 账号页“少放的歌手”；播放页“少放这类”的提示语只承诺“之后的推荐会少放”。

## 已知不完美，不是遗漏
- 旧节目和后端内置的两档老种子节目没有封面短标题，封面仍可能不放字。
- “少放”只到歌手级，不重做正在播放的节目，没有曲目级。
- 分享链接预览图在取不到字体时只有封面和品牌。
- 偏好只做了 demo 级；标题质量在简短请求上仍偏平，以真实使用反馈为准。
- 生产只有一套环境：预览里的功能性验收做不了，发布后要在 wavecast.space 上走 release-readiness 里的验收清单。
