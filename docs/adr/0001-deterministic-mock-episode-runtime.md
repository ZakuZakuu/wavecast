# ADR 0001: Use a deterministic, in-memory runtime for the mock vertical slice

## Context

The first milestone needs to validate progressive episode semantics without paid providers, queue infrastructure, or a music-catalog credential.

## Decision

The API owns an `EpisodeOrchestrator` backed by an in-memory repository. It progresses a fixed mock program one segment at a time only while a listener is active. The web player polls that deterministic progression and renders a heterogeneous timeline. Provider protocols and fake adapters exist, but fake generation is not delegated authority over episode lifecycle.

## Alternatives considered

- Generate a static full episode on card click. Rejected because it cannot validate frontiers, cancellation, or latency hiding.
- Embed runtime decisions in a frontend store. Rejected because persisted/runtime invariants belong to the backend boundary.
- Integrate real AI and TTS during Phase 1. Rejected for cost, credentials, and test determinism.

## Consequences

The slice is simple to test and requires no configuration. State disappears on server restart and mocked tones are not real songs; Phase 2 must add persistence and actual provider adapters without changing the orchestration contract.

