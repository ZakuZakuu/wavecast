# Claude 云端节目精校环境

2026-10-08。独立运行修改后的 API、测试数据库和音频目录；不改 Railway/Vercel，
不连接正式用户数据库。先建立可复现基线，再精校内容。当前代码基线为 integration。

## 用户配置

在 Claude Cloud 新建 `WaveCast Programme Review` 环境，Network access 选 Full。
下面粘贴到 Environment variables；将占位值换成专用开发 key，不要将真实值提交或
贴进对话。没有需要导入的生产 DB、OAuth、Resend 或 Better Auth 密钥。

```dotenv
WAVECAST_PROVIDER_MODE=mock
WAVECAST_RECOMMENDATION_PLANNER=deterministic
DEEPSEEK_API_KEY=<开发专用 key>
EXA_API_KEY=<开发专用 key>
TAVILY_API_KEY=<开发专用 key>
MINIMAX_API_KEY=<开发专用 key>
NETEASE_MUSIC_API_BASE_URL=http://127.0.0.1:3101
NETEASE_UPSTREAM_BASE_URL=http://127.0.0.1:3100
NETEASE_UPSTREAM_TIMEOUT_SECONDS=10
ENABLE_RANDOM_CN_IP=true
ENABLE_FLAC=false
ENABLE_GENERAL_UNBLOCK=false
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
DEEPSEEK_TIMEOUT_SECONDS=20
DEEPSEEK_DEEP_TIMEOUT_SECONDS=60
DEEPSEEK_MAX_OUTPUT_TOKENS=4096
DEEPSEEK_DEEP_MAX_OUTPUT_TOKENS=12288
MINIMAX_TTS_BASE_URL=https://api.minimax.cn
MINIMAX_TTS_MODEL=speech-2.8-turbo
MINIMAX_TTS_VOICE_ID=<当前选用的 voice ID>
MINIMAX_TTS_SPEED=0.8
MINIMAX_TTS_LANGUAGE_BOOST=auto
WAVECAST_INTERNAL_API_URL=http://127.0.0.1:8000
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

模型/TTS 行是仓库默认值，不是已核实的线上配置。首次对照时让用户确认生产的
非秘密模型、音色、速度，再保持一致。本方案不需要 Railway 地址或 Audius key。
两个 localhost 地址不是同一个服务：WaveCast → sidecar 3101 → upstream 3100
（原生 Node，监听 127.0.0.1:3100；`--docker` 时容器内部 3000）。Next 前端仍用 3000，因此不要把 upstream 映射到主机 3000。

第一版使用普通环境变量。Network secrets 注入 HTTP header，但程序还检查 key
环境变量，Tavily 当前也在请求 JSON 里传 api_key；尚未实现/验证代理注入兼容。
不要填一个假 key 然后当成兼容。分别设开发额度，优先复用一次生成结果。

## Setup script（只安装工具）

将仓库 `scripts/cloud/setup.sh` 的完整内容粘贴到环境 Setup script，不要在那里
启动 API 或生成节目。它在 root Ubuntu 中安装 FFmpeg/Postgres/uv/Python 3.12。
设置首次执行后会缓存文件，但不会保留运行进程；启动服务仍在每次会话执行。
若安装超过平台约五分钟预算，移到会话执行并记录失败，不要无限重试。
官方环境说明：https://code.claude.com/docs/en/cloud-environments

## 云端本地音乐链路（替代 Railway）

Claude 会话关联主仓 `ZakuZakuu/wavecast`，还需要读取副仓
`ZakuZakuu/wavecast-music-dev`。副仓当前为公开仓库（2026-10-08 已核对），可匿名读取；如果
云端代理拒绝读取副仓，先检查访问配置或由用户提供副仓源码，不改仓库可见性，
不往环境里加全权限 GitHub token 来绕开限制。

先在会话运行（独立后台任务，不放进 VM Setup script）：

```bash
bash scripts/cloud/start-music.sh
```

脚本默认**原生运行**：将副仓 clone 到 gitignored 数据目录并打印版本 SHA；按固定上游
commit `a8c781fd64faab17fedfd46e0615a2609307f163` 在 `.wavecast-data/cloud/ncm-upstream`
拉取，`pnpm@9 install --frozen-lockfile --prod --ignore-scripts` 后用 Node 监听
127.0.0.1:3100（日志与 pid 在 `.wavecast-data/cloud/`），再启动 native Python sidecar 于
127.0.0.1:3101。原生是默认值，因为 Claude 云端 Docker 构建不信任沙箱代理 CA，
且 Docker Hub 匿名拉取会 429 限流。不会调用模型、搜索或 TTS。不会自动更新已 clone
的副仓；3100 已有监听时拒绝启动，需先核对进程。

`bash scripts/cloud/start-music.sh --docker` 保留原容器流程（`Dockerfile.upstream`），仅在
有 Docker daemon 且构建不经代理时使用；云端 VM 里 `dockerd` 默认不运行。

启动后先检查 `/health`（仅进程），再检查 `/ready`（一次有界目录请求）：

```bash
curl --fail --silent http://127.0.0.1:3101/health
curl --fail --silent http://127.0.0.1:3101/ready
```

再验收一个指定歌曲的 search → track → playback → 音频可下载，按副仓 README
合同读取。播放 URL 可能带签名，不输出到对话/日志/提交。请求成功不等于歌曲全长
可播；应检查下载内容类型/时长。音乐链路失败时不开始付费节目生成。
启动阶段 `xeapi public key is missing` 单行不是退出证据：副仓 README 解释了后续
自动获取 key 的 bootstrap 顺序；核对监听端口、后续日志和退出状态。不添加 Cookie、
登录或手工 key 来消除该提示，不改变地域/付费限制相关开关。

上游的 `ENABLE_RANDOM_CN_IP`、`ENABLE_FLAC`、`ENABLE_GENERAL_UNBLOCK` 按用户在 2026-10-08
提供的生产设置镜像（`true`/`false`/`false`；生产端口 3000 在本地仍用 3100）。这三项在上方的
环境变量里设置即可，`start-music.sh` 启动的上游会继承它们；不设置时上游默认全部关闭。

**上游风控（2026-10-08 实测）：** 云端 VM 是海外云 IP。短时间内较多请求后，NetEase 会返回
`code -460「检测到您的网络环境存在风险，请稍后再试」`，sidecar 对外表现为 502
`music upstream unavailable`，持续数分钟。观察到启用随机国内 IP 后**仍然会被拒绝**：它只改
请求头，不改 TCP 出口 IP，所以不能当作解决办法。实际做法：

- 评审实验之间留出间隔，不要连续多轮生成或探针；
- 出现连续 502 时先停手，只用 `/ready` 做低频探测，数分钟后再继续；
- WaveCast 侧的 sidecar 适配器对 `search` 与曲目详情做短时缓存、合并相同请求，并在连续临时
  失败后暂停新请求（`providers/call_guard.py`），避免失败期间继续加重限制。

两服务只在 Claude VM 中运行，不请求 Railway；网络仍会访问音乐平台。
重启时先停止上游（`kill $(cat .wavecast-data/cloud/ncm-upstream.pid)`）和 sidecar 再运行；
`--docker` 模式则 `docker stop wavecast-cloud-netease`。不要清理其他进程或 Docker 资源。
2026-10-08 在 Claude 云端验证：原生链路 `/health`、`/ready`、search → playback → 音频下载
（全长时长与元数据一致）通过；副仓为公开仓库，匿名读取可用。版权受限曲目（如周杰伦原唱）
无法播放属预期，选题时需避开。

## 每次会话：从 mock 到真实基线

读 AGENTS、PRELIMINARY_PRODUCT_TARGET、PROJECT_STATE，再只读本任务相关代码。
基于最新 integration 开功能分支；不要切到旧宣传片/海报分支。

```bash
uv sync --locked --all-groups
bash scripts/cloud/start-api.sh --mock
```

启动脚本用本机 `wavecast_cloud` 数据库和 `.wavecast-data/cloud/audio`；覆盖生产 DB
URL，取消认证验证变量，先迁移再以前台方式启动 API。让 Claude 在独立后台任务中
运行；不要加 `--reload`，避免编辑时中断 worker。另一个终端 GET
`http://127.0.0.1:8000/api/health` 检查服务。脚本需要 cloud root + service/runuser。
已有同名 role/DB 会保留，密码未主动重置；认证失败先诊断，不删除数据。

需要网页时另行准备 Node（仓库 README 要求 Node 24+）和 pnpm 10.12.1，再运行：

```bash
pnpm install --frozen-lockfile --filter @wavecast/web...
pnpm dev:web
```

本地前端使用相同 origin 的代理，云端 localhost **不是用户手机可直接打开的地址**。
Claude 可在其浏览器或本地工具验收；用户听感验收需导出音频文件，或之后建立一次
integration 托管检查点。不要假设平台已提供公开端口。

确认配置和音乐可达后停掉 mock API，只启动一份 live API：

```bash
bash scripts/cloud/start-api.sh --live
```

只想评审选曲和文稿、不合成语音时用 `bash scripts/cloud/start-api.sh --live --no-tts`：
研究、选曲、写稿仍走真实 provider，TTS 用 mock（不调用 MiniMax，也不要求 MiniMax key/voice ID，时长为估算值）。

`--live` 显式打开现有各阶段，包括 MiniMax，配置检查不会发 provider 请求；
服务启动后新建节目会花费额度。先从本地 API `/docs` 核对请求合同，使用固定的
`X-Wavecast-Listener`（如 `claude-review-01`）贯穿提案、开播、获取、渲染请求。
按实际网页的提案 → from-seed → 渐进生成/播放 checkpoint → program-render 流程
建立基线。全片验收可显式调用一次 materialize 并轮询只读 GET；该 full 模式与
progressive 体验不同，不能证明开播延迟或续播稳定性。

**单次测试不是单次模型调用。** ProviderSettings 默认 max_attempts=2，结构化输出
和 worker 也有既有恢复行为。没有一个已实现的 env 开关保证整个运行时不重试。
不要连续重发 ensure-buffer/materialize，不要自动重复创建节目；失败先停服务并
诊断。严格单请求探针要先审查调用路径；本任务不擅自改正式重试策略。

旧 `scripts/live_episode_probe.py` 可做显式一次离线 assembly 实验，但不等同线上
渐进运行时，也不能用 probe 的 track/chapter 上限当产品规则。初始基线优先 API。
普通 pytest 保持 mock；不要将 live key + live 模式用于普通测试。

## 读取节目与精校

读取已生成的本地节目，不新生成、不渲染、不调用付费接口：

```bash
uv run python scripts/cloud/export-review.py <episode-id> --listener-id claude-review-01
```

结果在 gitignored `.wavecast-data/cloud/reviews/<episode-id>.json`：选曲、章节 ID、
可见主持词、TTS 文本/cues、状态和时长；不包含音源 URL、用户身份或 provider 原始
请求/响应。此导出不是研究证据包。API 的 progressive_session 不公开；需要核对
事实来源时，针对该本地数据库加载已存储的结构化研究结果，另外做白名单导出。
禁止 dump 全表/原始 prompt/response/reasoning。没有来源不能当作核实过的事实。

导出文件还带 `usage`（来自 `GET /api/episodes/<id>/usage`，仅所有者可读）：节目的预估/
实际时长、音乐与口播段数、被跳过的口播数，以及该节目各阶段的 provider 调用次数、耗时、
token/字符/成本。用量保存在 API 进程内存里（有上限，重启即清空），只用于评审一次生成，
不是账单。API 日志同时输出 `provider_call …`（每次调用的阶段、耗时、用量）、
`catalog_pool_ready … failure_kinds={…}`（目录失败按 provider:异常类型计数，区分不可用、
凭据被拒、限流）和 `episode_materialized …`（预估对实际时长）；都不含 prompt、响应、URL。

先固定一个主题形成 baseline。标注：是否回答选题、事实依据、曲目与路线关系、
口语自然程度、重复套话、转场/收尾、目标与实际时长；听感另看主持位置、压人声、
停顿和音色。每条批评附具体片段及预期改进，不只写“更自然”。
段落总时长相加不等于 mix 时长（有重叠主持）；planned、audio-ready 和已发布前缀
要分开，不把生成中短前缀当成完整节目。

优先读取同一份结构化研究/选曲结果对照 Writer 修改；现有项目没有通用阶段回放
命令，若需要先做最小复用工具，再评估新增付费 calls。不要宣称自动缓存了所有阶段。
文字精校确定后再对选定版本生成 TTS/渲染，避免每次改文案整档重跑。

本地 PG/音频跨 API 重启保留，但云端 VM 可能回收，不是长期备份。会话结束导出
所需评审/试听文件给用户；密钥、签名 URL、用户数据不随文件分享、不入 git。

## 交付与边界

交付：具体问题清单、baseline/修改版对照、代码 PR → integration、实际 checks、
调用次数/已知成本元数据及没验收的部分。不要自行合并 release 或部署 production。
本轮先精校研究/策划/主持词/TTS，保持音乐连续性和既有不可变前缀，不广泛重构播放器。
#171–#173 可按证据单独处理，不顺带改首页或账号体系。

仓库脚本的静态/无付费验证不代表 Claude VM、音乐上游或真实生成已验收；第一次
云端开机后先做 mock，再按用户授权进行一档 live，失败停止诊断。
