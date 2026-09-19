# ADR 0012: Deterministic Program Timing

## Status

Accepted and implemented in Phase 4.8.3.

## Context

WaveCast must honor a requested program duration without turning the Writer,
TTS provider, or playback clock into a lifecycle authority. Music duration is
known only after the selected tracks cross the catalog and playback-asset
boundary. Narration duration is not reliable until the TTS asset exists.
Previous assembly allocated one equal narration target to every chapter and
did not expose planned-versus-actual drift.

## Decision

1. Application code owns the timing plan. It computes requested, available,
   and allocated narration seconds before Writer runs.
2. Prepared music assets are the source of truth for resolved music duration.
   Each track asset is fetched once and then reused for composition.
3. Chapter narration budgets are deterministic and weighted by the number of
   real narration slots, with integer remainder assignment by chapter index.
   The Writer receives a chapter-specific total spoken budget for all blocks
   it returns; it does not decide block count or playback placement.
4. TTS asset duration is the source of actual narration duration. The runtime
   records planned narration, actual narration, planned total, actual total,
   ratios, and signed drift in a safe timing summary.
5. Desired duration is a target, not a hard constraint. If music leaves less
   room than the requested narration budget, narration is compressed. If
   music fills or exceeds the target, or the remaining room is smaller than
   the deterministic minimum narration budget required to preserve existing
   chapters, the plan is explicitly infeasible; existing chapters still
   receive a deterministic minimum budget and no chapter or editorial content
   is silently deleted.
6. Timing drift does not trigger an implicit Writer or TTS retry. Timing does
   not rewrite committed/editorial content, trim tracks, add fades, or ask an
   LLM to delete chapters.
7. Phase 4.8.3 remains credential-free. Phase 4.8.3.2 adds derived
   buffer-ahead runtime accounting without introducing a server playback clock.

## Alternatives considered

- Let Writer choose narration lengths: rejected because it makes duration and
  editorial placement nondeterministic.
- Fetch music again during composition: rejected because it can change the
  duration observed by the Writer and creates avoidable provider work.
- Force every episode to hit its target exactly: rejected because it would
  require silent track mutation, chapter deletion, or unbounded retries.
- Retry when TTS duration drifts: rejected because drift is an observable
  provider result, not a lifecycle failure.

## Consequences

- Timing decisions are testable without provider credentials.
- The system can explain why a target was compressed or infeasible.
- Planned and actual durations may differ; callers must use the summary rather
  than assuming the requested duration is exact.
- The existing slot-placement, frontier, commitment, provider, and published
  immutability contracts remain unchanged.
