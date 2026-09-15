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

Search adapters retain their short 20-second timeout. DeepSeek structured synthesis has its own
optional, bounded configuration: `DEEPSEEK_TIMEOUT_SECONDS=20` and
`DEEPSEEK_MAX_OUTPUT_TOKENS=4096`. These are defaults, not required environment variables; the
output limit bounds a single response without disabling model reasoning or adding another attempt.
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

## Current scope

Phase 1.5 adds a durable Postgres repository, listener-scoped resume, and version-polled SSE while retaining mock-mode development. Phase 2 adds independent DeepSeek, Exa, and Tavily adapters with a deterministic discovery/research router and in-memory usage ledger. Real calls remain opt-in; the episode runtime, frontend, TTS, and full agent pipeline remain unchanged until later milestones.
