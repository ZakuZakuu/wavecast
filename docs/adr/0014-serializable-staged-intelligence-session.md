# ADR 0014: Serializable staged intelligence session

- Status: Proposed
- Date: 2026-09-23

## Context

Phase 7A provides an opening-only runtime, bounded buffer generation, atomic
complete-chapter appends, and persisted next-chapter identity. The production
intelligence path still runs as one full `LiveEpisodeAssemblyService.assemble()`
operation. Reusing that operation for every buffer refill would repeat research,
curation, route resolution, writing, and TTS work.

A staged adapter must also avoid recreating the Phase 7A failure mode in which
process-local progress becomes the source of truth.

## Decision

Introduce a provider-neutral `ProgressiveAssemblySession` snapshot in the
sanitized assembly result. It stores normalized fast-start, research, curation,
resolved-route, narration-slot, timing, and safe diagnostic data. It is
round-trippable through Pydantic JSON and contains no provider client, raw
provider response, credential, hidden reasoning, or ephemeral playback URL.

The snapshot exposes a pure `next_chapter(LiveEpisode)` lookup. It derives the
first route chapter absent from persisted timeline chapter IDs. No mutable
session cursor is authoritative.

This 7B.1 contract does not replace the Phase 7A default generator or connect
live providers. A later slice may use the snapshot to implement staged
resolution, Writer, composition, and TTS behind the existing
`ProgressiveChapterGenerator` boundary.

## Consequences

- Research and curation can be initialized once and reconstructed from data.
- Leave/resume and process reconstruction retain persisted-timeline ownership of
  chapter progress.
- The current full assembly behavior remains available and its web contract is
  unchanged.
- The snapshot increases the sanitized assembly artifact size; later work must
  keep its fields normalized and safe.
