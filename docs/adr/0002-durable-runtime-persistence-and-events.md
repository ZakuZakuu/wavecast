# ADR 0002: Persist episode snapshots in Postgres and publish state through SSE

## Context

Phase 1 proved deterministic playback semantics in memory. The next milestone requires a listener to recover a live timeline after an API restart, without prematurely introducing workers, Kafka, Temporal, or real AI providers.

## Decision

`EpisodeRepository` is the persistence boundary used by `EpisodeOrchestrator`. `InMemoryEpisodeRepository` remains the default for zero-credential mock development and unit tests. `PostgresEpisodeRepository` uses SQLAlchemy 2's asyncpg dialect and stores the complete typed `LiveEpisode` snapshot, including every `Segment`, as a versioned JSONB payload plus indexed listener/seed identity columns. Postgres is therefore the source of truth for state recovery and SSE polling.

Every persistence write is compare-and-swap: a snapshot at version `N` only updates the matching row at version `N`, then becomes `N + 1`. A stale snapshot raises an explicit retryable conflict and cannot roll back a newer materialized or playback state. SSE is intentionally version-polled from Postgres; its async coroutine offloads synchronous repository/orchestrator reads to a worker thread, so the adapter never invokes `asyncio.run()` inside the API event loop.

An anonymous, stable browser ID scopes an episode by `(listener_id, seed_id)`; it is deliberately not an authentication system. The API accepts an `X-Wavecast-Listener` header and also maintains a same-site cookie fallback.

The API exposes an SSE endpoint which polls the repository version and emits `episode_state_changed` snapshots. The web client consumes the same-origin EventSource using its cookie-scoped anonymous identity and applies only newer snapshots. `GenerationScheduler` is an explicit seam with an inline implementation only. Browser audio completion reports a lifecycle event to the API; a browser-local clock calculates segment-relative offsets and periodically checkpoints valid positions, so the browser no longer advances the server clock every second.

## Alternatives considered

- Redis/Kafka/Temporal/worker queue now: rejected; a durable DB snapshot and polling SSE are sufficient for this milestone.
- Full authentication: rejected; listener isolation is needed before account semantics.
- DB-owned state transitions: rejected; the deterministic orchestrator remains the sole owner of runtime decisions.
- One table per segment immediately: deferred. JSONB snapshots preserve all segment state atomically while the program schema is still evolving; normalized projections can follow with real agents and reporting needs.

## Consequences

Postgres development is available with Docker Compose and Alembic. Mock mode stays the default when `WAVECAST_DATABASE_URL` is absent. The adapter uses short-lived async connections behind the existing synchronous orchestrator boundary; Phase 2/worker work may make orchestration fully async without changing persistence semantics. Milestone ordering is now: Phase 1 mock runtime → Phase 1.5 durable runtime → Phase 2 real providers → Phase 3 bounded agent pipeline.
