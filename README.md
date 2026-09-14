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

## Validation

```bash
uv run ruff check .
uv run mypy
uv run pytest
pnpm lint
pnpm typecheck
pnpm test:web
pnpm build
```

## Current scope

Phase 1 implements an in-memory, mock-only vertical slice. It is intentionally not durable across a server restart and uses browser-generated placeholder tones rather than licensed audio. The application boundary is already separated into domain models, deterministic orchestration, and provider protocols so real adapters and persistence can replace these seams in later phases.

