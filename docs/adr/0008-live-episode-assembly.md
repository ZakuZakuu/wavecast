# ADR 0008: Assemble a bounded playable episode through provider-neutral seams

## Context

The first real listening slice must connect progressive intelligence to the
existing browser-playable timeline without allowing an LLM proposal or a
provider payload to bypass deterministic application boundaries.  Research and
curation can produce unresolved artist/title proposals, while playback needs a
stable catalog identity and an audio asset.  Narration is already materialized
through the provider-neutral TTS and object-storage seams.

## Decision

`LiveEpisodeAssemblyService` is the application-level join between the existing
`FastPathCoordinator`, cancellable background research/curation, deterministic
proposal resolution, `WriterService`, `EpisodeComposer`, and
`NarrationMaterializer`.

For each bounded request it:

1. runs the existing fast path and preserves its first-script trace;
2. runs background research and Curator in narrative order;
3. resolves each selected `TrackProposal` through `MusicRetrievalService` and
   `resolve_track_proposal_across_providers`;
4. reports unresolved proposals and skips them, failing with a typed
   `EpisodeAssemblyError` when fewer than two playable tracks remain;
5. invokes Writer only after resolution, passing prior script context and the
   typed resolved narration-slot context described in ADR 0011;
6. normalizes the returned radio blocks once, keeping opening music first,
   indexed track intros in their gaps, transitions between tracks, and one
   final outro;
7. composes provider-neutral music assets and materializes every narration
   segment through the existing storage/TTS boundary.

The mock factory uses deterministic search, catalog, LLM, TTS, and local asset
providers with zero credentials.  The live factory uses the configured
DeepSeek, Exa, Tavily, real MusicProvider registry, MiniMax, and local storage;
it fails clearly when no real music provider is configured and never falls back
to a mock provider in live mode.  `scripts/live_episode_probe.py` is opt-in and
loads the repository-local `.env`; CI never invokes it.

## Alternatives considered

- Let `EpisodeOrchestrator` own assembly: rejected because the orchestrator is
  the deterministic episode lifecycle boundary, not an AI pipeline coordinator.
- Pass unresolved proposals to `EpisodeComposer`: rejected because an
  unresolved artist/title pair is not a playable catalog identity.
- Materialize a complete episode before returning: rejected because progressive
  research and the existing bounded playback frontier should remain intact.
- Add a queue or workflow engine: deferred; one bounded inline async service is
  sufficient for the current milestone.

## Consequences

The mock and live modes exercise the same application path, and the result is
an inspectable `PlayableEpisode` with resolved tracks, materialized narration,
safe usage totals, stage timings, unresolved-proposal diagnostics, and a
duration breakdown.  The service does not persist a new episode lifecycle or
change browser-owned playback state; connecting the result to a durable
episode endpoint remains a follow-up integration step.
