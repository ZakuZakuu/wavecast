# ADR 0001: Use a deterministic, in-memory runtime for the mock vertical slice

## Context

The first milestone needs to validate progressive episode semantics without paid providers, queue infrastructure, or a music-catalog credential.

## Decision

The API owns an `EpisodeOrchestrator` backed by an in-memory repository. It owns a logical playback clock: completed segments become `PLAYED`, contiguous ready segments start automatically, and unready narration skipped by `Next` is explicitly removed from the active timeline as `SKIPPED`. It only materializes one or two complete future chapters through `ensure_buffer`, and only while a listener heartbeat is active. A 30-second TTL stops speculative work if navigation/unload prevents a clean leave request.

The web player drives one-second mock clock ticks and heartbeats, renders the heterogeneous timeline, and sends a best-effort leave on unmount/page exit. Re-entering a seed resolves its existing in-memory episode before creating a new one. Provider protocols and fake adapters exist, but fake generation is not delegated authority over episode lifecycle.

## Alternatives considered

- Generate a static full episode on card click. Rejected because it cannot validate frontiers, cancellation, or latency hiding.
- Embed runtime decisions in a frontend store. Rejected because persisted/runtime invariants belong to the backend boundary.
- Integrate real AI and TTS during Phase 1. Rejected for cost, credentials, and test determinism.

## Consequences

The slice is simple to test and requires no configuration. State disappears on server restart and mocked tones are not real songs; Phase 2 must add persistence and actual provider adapters without changing the orchestration contract. The program promise duration is intentionally distinct from the current mock timeline duration.
