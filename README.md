# Wavecast

Wavecast is an AI-native guided-listening radio product. The first vertical slice deliberately runs entirely on deterministic fake providers: opening music is immediately playable, while future narration and tracks become available incrementally.

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
`DEEPSEEK_DEEP_TIMEOUT_SECONDS=45` for background DEEP/Curator inference, plus
`DEEPSEEK_MAX_OUTPUT_TOKENS=4096` and
`DEEPSEEK_DEEP_MAX_OUTPUT_TOKENS=12288`. These are defaults, not required environment variables; the
hot-path timeout remains 20 seconds, while only the background DEEP profile receives the longer
bounded budget. The output limit bounds a single response without disabling model reasoning or
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
with distinct local-similarity, scene-bridge, and cross-scene roles. Generic search results remain
Evidence; FastStart and Curator infer candidates downstream. The opt-in evaluator runs at most two
bounded cases and records only sanitized review artifacts:

```bash
uv run --env-file .env python scripts/live_curation_eval.py
```

Evaluation output is for human review and does not automatically claim a quality pass. Do not
commit raw provider responses, prompts, reasoning, credentials, or unreviewed quality claims.

## Current scope

Phase 1.5 adds a durable Postgres repository, listener-scoped resume, and version-polled SSE while retaining mock-mode development. Phase 2 adds independent DeepSeek, Exa, and Tavily adapters with a deterministic discovery/research router and in-memory usage ledger. Phase 3 adds a two-speed, typed progressive intelligence pipeline and TTFS tracing without wiring it into EpisodeOrchestrator or adding TTS. Real calls remain opt-in; the frontend and episode runtime remain unchanged.
