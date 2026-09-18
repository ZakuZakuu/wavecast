# Wavecast

Wavecast is an AI-native guided-listening radio product. The first vertical slice deliberately runs entirely on deterministic fake providers: opening music is immediately playable, while future narration and tracks become available incrementally.

For a fast project handoff, start with [the current project state](docs/PROJECT_STATE.md), then read the [long-lived Codex handoff](docs/CODEX_HANDOFF.md). Architecture decisions are recorded in [`docs/adr/`](docs/adr/).

## Development

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 24+, and pnpm 10+.

```bash
uv sync --all-groups
pnpm install
uv run uvicorn services.api.main:app --reload --port 8000
pnpm dev:web
```

Open `http://localhost:3000`. No API keys are needed. The frontend proxies `/api/*` to the FastAPI server during development.

### Durable runtime (optional Postgres)

Mock mode is the default. To exercise restart-safe episode state, start the included database and apply the migration:

```bash
docker compose up -d postgres
export WAVECAST_DATABASE_URL=postgresql+asyncpg://wavecast:wavecast@127.0.0.1:5432/wavecast
uv run alembic upgrade head
uv run uvicorn services.api.main:app --reload --port 8000
```

To run the real Postgres integration test, set `WAVECAST_TEST_DATABASE_URL` to the same URL. All other tests remain credential-free and use the in-memory repository.

### Phase 2 provider probes (explicitly opt-in)

Provider mode defaults to `mock`; neither development nor CI calls paid services. To run a real probe, copy `.env.example` to the gitignored local `.env`, set `WAVECAST_PROVIDER_MODE=live`, and fill only the local `DEEPSEEK_API_KEY`, `EXA_API_KEY`, and `TAVILY_API_KEY`. Never commit `.env` and do not put provider keys into shell history.

Run every paid command with uv's explicit env-file loading:

```bash
uv run --env-file .env python scripts/live_provider_smoke.py
uv run --env-file .env python scripts/live_research_probe.py \
  --anchor "3rd Coast - Jealousy" \
  --anchor "3rd Coast - Luv is True" \
  --json-output /tmp/wavecast-3rd-coast.json
uv run --env-file .env pytest tests/live --run-live
```

The smoke command also accepts `--provider deepseek`, `--provider exa`, or `--provider tavily`.
The bounded 3rd Coast probe makes at most two Exa searches, three Tavily searches, and one
DeepSeek synthesis request. It is a manual provider-quality evaluation, not the production agent
pipeline and never connects to `EpisodeOrchestrator`. The scripts print only compact normalized summaries and usage totals; provider secrets and raw provider responses are not written to the repository.

The opt-in MiniMax narration probe loads the repository-local `.env` itself, so it can be run
directly without exporting provider variables or passing `--env-file`:

```bash
uv run python scripts/minimax_tts_probe.py --run-live
```

For this probe only, values from `.env` take precedence over stale exported provider variables.

Search adapters retain their short 20-second timeout. DeepSeek structured synthesis has its own
optional, bounded configuration: `DEEPSEEK_TIMEOUT_SECONDS=20` and
`DEEPSEEK_DEEP_TIMEOUT_SECONDS=60` for background DEEP/Curator inference, plus
`DEEPSEEK_MAX_OUTPUT_TOKENS=4096` and
`DEEPSEEK_DEEP_MAX_OUTPUT_TOKENS=12288`. These are defaults, not required environment variables; the
hot-path timeout remains 20 seconds, while only the background DEEP profile receives the longer
bounded budget. The dedicated Curator profile keeps the same deep-sized timeout and
12288-token cap while using low reasoning effort; the general DEEP profile remains high
reasoning. The output limit bounds a single response without disabling model reasoning or
adding another attempt.
The diagnostic 3rd Coast probe locally overrides only its DeepSeek call to a 90-second timeout;
the reusable provider default remains 20 seconds.

## Validation

```bash
uv run ruff check .
uv run mypy
uv run pytest
uv run --env-file .env pytest tests/live --run-live  # explicitly makes small paid calls
pnpm lint
pnpm typecheck
pnpm test:web
pnpm build
```

### Phase 3 progressive intelligence (manual, paid opt-in)

The Phase 3 pipeline keeps the episode runtime unchanged. Its fast path runs one Exa and one
Tavily query concurrently, then one DeepSeek Responses JSON Schema call for a typed
`FastStartPlan` under a 15-second hard deadline. A cancellable background path adds at most one
Exa and two Tavily queries before Curator/Writer produce a broader typed arc and one future script.
Run the sanitized live evaluation only after credential-free validation:

```bash
uv run --env-file .env python scripts/live_progressive_probe.py \
  --anchor "3rd Coast - Jealousy" \
  --anchor "3rd Coast - Luv is True"
```

It prints TTFS, stage usage, candidate counts, a novelty-distance curve, and a compact quality
summary. It never prints raw provider responses or reasoning text. The command is explicitly paid
and bounded; do not run it from ordinary tests or CI.

### Phase 3.5 editorial and curation quality

Guided Discovery quality is evaluated separately from runtime correctness. The credential-free
benchmark cases and typed human-review rubric live under `backend/wavecast/evals/`; they cover
same-artist traps, game-music context, artist-to-scene bridges, and mood-driven discovery without
prescribing exact answers. Search remains bounded at one Exa plus two Tavily background queries,
with routing selected by the topic-adaptive ResearchPlan. Generic search results remain
Evidence; FastStart and Curator infer candidates downstream. The opt-in evaluator runs at most two
bounded cases and records only sanitized review artifacts:

```bash
uv run --env-file .env python scripts/live_curation_eval.py
```

Evaluation output is for human review and does not automatically claim a quality pass. Do not
commit raw provider responses, prompts, reasoning, credentials, or unreviewed quality claims.

### Phase 4.5 live episode assembly (manual, paid opt-in)

`LiveEpisodeAssemblyService` joins the existing fast/background intelligence path to deterministic
catalog resolution, radio-script composition, provider music assets, and MiniMax narration
materialization. Mock mode uses the same path with zero credentials. The live assembly probe is
never run by CI and loads the repository-local `.env` only after explicit authorization:

```bash
uv run python scripts/live_episode_probe.py --run-live \
  --topic "guided listening around 3rd Coast" \
  --anchor "3rd Coast - Jealousy" \
  --anchor "3rd Coast - Luv is True" \
  --max-tracks 4 \
  --json-output /tmp/wavecast-live-episode.json
```

The probe prints only stage timings, safe usage totals, resolved catalog identities, and timeline
metadata. It fails clearly if live mode has no configured real music provider; it never substitutes
mock music or narration in live mode.

### Phase 4.6 adaptive research planning

FastStart now emits a topic-adaptive `ResearchPlan` in the same structured call as the first
script. The plan contains an open central question, bounded facets, and a defensively bounded
pool of zero to eight proposed queries. The deterministic background stage routes `DISCOVERY` to
Exa and `RESEARCH`/`EXACT` to Tavily, deduplicates fast queries, and executes at most one Exa plus
two Tavily calls. Generic search
results remain safe `Evidence` with facet/intent provenance; they do not become track proposals by
webpage title. Curator receives the plan and adapts its chapter beats to the request rather than
assuming a fixed discovery arc. The episode probe reports only sanitized plan metadata. No live
probe is part of CI.

### Phase 4.7 narrative-first structure and TTS-aware writing

Curator chapters are narrative beats with optional music, so an unresolved or
absent track removes only the music asset while the story continues through
Writer. Assembly allocates a bounded 10–20% narration budget from the requested
program duration. Requests carry `output_language` (`auto`, `zh-CN`, `en-US`, or
`ja-JP`); automatic selection uses the user topic. Radio blocks keep visible
editorial `text` separate from optional pronunciation-aware `tts_text`, and the
materializer uses the latter for TTS/cache identity without changing UI copy.
No new provider or live probe is part of this milestone.

## Current scope

Phase 1.5 adds a durable Postgres repository, listener-scoped resume, and version-polled SSE while retaining mock-mode development. Phase 2 adds independent DeepSeek, Exa, and Tavily adapters with a deterministic search router and in-memory usage ledger. Phase 3 adds a two-speed, typed progressive intelligence pipeline and TTFS tracing. Phase 3.5 hardens editorial evaluation. Phase 4 adds provider-neutral music assets, deterministic radio composition, and MiniMax narration materialization. Phase 4.5 assembles those seams into one bounded playable episode. Phase 4.6 adds topic-adaptive research planning without changing runtime, playback, or live budgets. Phase 4.7 adds narrative-first chapters, bounded narration budgeting, explicit spoken-language selection, and TTS-aware visible/synthesized text separation; it does not add a queue, new provider, recommendation redesign, or browser playback redesign. Real calls remain opt-in.
