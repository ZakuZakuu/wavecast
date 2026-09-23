# ADR 0015: Durable staged runtime adapter

- Status: Accepted
- Date: 2026-09-24

## Context

Phase 7B.1 introduced a serializable ProgressiveAssemblySession, and Phase
7B.2 introduced a chapter-at-a-time generator. The runtime still used the
deterministic mock generator because the session was not attached to the
persisted LiveEpisode.

Repeating research and curation after a restart would waste provider work and
could change the route. Keeping a generator, cursor, or session map in process
memory would also violate the persisted timeline as the source of truth.

## Decision

Persist the typed ProgressiveAssemblySession inside the existing episode JSONB
snapshot. The field is excluded from ordinary LiveEpisode serialization so
public API responses and SSE events do not expose research, evidence, slot
contexts, or timing internals. The Postgres repository explicitly adds the
sanitized session payload when it is present; snapshots without the field
remain valid legacy episodes.

StagedProgressiveRuntimeAdapter reconstructs an assembly request only from the
episode topic, estimated duration, and the persisted chapter-1 opening
identity. It creates a fresh chapter generator from the persisted session for
each generation call. It owns no cursor, chapter progress, session map, or
episode mutation.

Within the existing per-episode scheduler lock, preparation occurs outside
episode mutation. The completed session is attached only after reloading the
latest episode and validating listener activity, lifecycle, and the structural
timeline anchor. Heartbeat/version-only changes do not invalidate preparation.
A leave, materialized transition, or structural change discards the prepared
session. If concurrent preparation loses a CAS race, the winner's durable
session is reused; no generic retry loop is added.

The session is persisted before Writer, music preparation, or TTS for the next
chapter. Therefore a later request can regenerate a failed chapter without
rerunning research or curation. materialize_all_async() uses the same staged
adapter and drains the same persisted route. The legacy deterministic generator
remains the default when no staged runtime is configured.

## Consequences

- Fresh orchestrator instances can continue from a durable route without
  process-local state.
- Opening startup remains immediate and opening-only.
- Provider work is bounded by the existing scheduler and staged contracts.
- The API keeps its existing public response and SSE shapes.
- The session snapshot is larger than an opening-only episode, but remains
  provider-neutral and sanitized.
- Deployment, queues, live providers, and UI cache/download behavior remain
  outside this slice.
