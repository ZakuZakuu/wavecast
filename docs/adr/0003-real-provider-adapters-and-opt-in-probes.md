# ADR 0003: Isolate real provider adapters behind normalized contracts and opt-in probes

## Context

Phase 1.5 made episode state durable but intentionally kept all intelligence mocked. Before the
bounded Phase 3 agent pipeline can use paid services, Wavecast needs to establish that DeepSeek,
Exa, and Tavily are reliable through provider-neutral interfaces, that their output and errors are
normalized, and that a developer can inspect actual usage without ordinary development or CI
spending money.

## Decision

`DeepSeekLLMProvider`, `ExaSearchProvider`, and `TavilySearchProvider` are standalone async
adapters under `wavecast.providers`. They depend only on the existing `LLMProvider`/
`SearchProvider` contracts and return typed Pydantic data. DeepSeek uses its OpenAI-compatible
async client and JSON mode, validates the requested output model, and makes at most one retry for
retryable transport/provider failures or malformed structured output. Exa uses `POST /search` with
`type=auto` and lightweight highlights. Tavily uses Search with explicit `general` topic, no answer
or raw page body, explicit usage reporting, and a caller-selectable `basic`/`advanced` depth.

`SearchRouter` is deterministic: `DISCOVERY` selects Exa and `RESEARCH` selects Tavily. `EXACT`
is explicitly reserved for a later Serper adapter. Provider SDK/HTTP errors are mapped to Wavecast
provider errors, and short exponential backoff is limited to 429s, temporary unavailable responses,
and timeouts. Tavily's documented 432/433 package and pay-as-you-go usage limits are normalized as
`ProviderBudgetExceededError`, never as a generic malformed response.

An in-memory `UsageLedger` records provider-neutral events. It records tokens for DeepSeek, actual
Exa cost when returned, and Tavily credits when returned; it never invents an amount from missing
provider data. `WAVECAST_PROVIDER_MODE=mock` remains the credential-free default. Live unit tests,
smoke tests, and the bounded 3rd Coast research probe require explicit live configuration and the
`--run-live` switch. Their documented commands use `uv run --env-file .env`, so credentials stay in
the ignored local file rather than shell history. Providers own and close their async clients through
async context managers even when a probe fails. Live checks are not invoked by CI.

These adapters, router, and probe do not connect to `EpisodeOrchestrator`, alter the durable runtime,
generate narration, or implement agent roles.

## Alternatives considered

- Connect providers immediately to episode materialization. Rejected: provider quality, spend, and
  error behavior need to be understood before they influence lifecycle decisions.
- Call Exa and Tavily for every query. Rejected: it is needlessly expensive and loses the explicit
  distinction between semantic discovery and factual research.
- Use a production queue and persistent cost ledger now. Rejected: the phase only needs bounded,
  manually invoked evaluation; durable job coordination belongs after the agent workflow exists.
- Permit tests to use credentials when present. Rejected: a local or CI environment with accidental
  credentials must still make zero paid calls unless a developer supplies `--run-live`.

## Consequences

Phase 3 can build bounded Research, Curator, Writer, and Replanner roles against stable provider
contracts, search intent routing, structured output, and usage observability. The current live probe
is deliberately not an evaluation golden fixture or recommendation workflow; any chosen real output
must be sanitized before being promoted into a fixture. The next milestone is the bounded Phase 3
agent pipeline, not frontend redesign, real TTS, or provider-owned episode transitions.
