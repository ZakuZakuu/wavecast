# ADR 0004: Use a two-speed progressive intelligence pipeline

## Context

The durable runtime now has normalized provider adapters, but a first narration must be ready
while opening music is already playing. A sequential research → curator → writer chain would put
three network/model stages on the critical path and make the first-script latency unpredictable.
The Phase 3 quality metric is Time To First Script (TTFS), not Time To First AI Audio (TTFA); TTS
remains a later milestone.

## Decision

Phase 3 has two deterministic application-owned paths:

- The fast path runs one bounded Exa context query and one bounded Tavily evidence query in
  parallel, deduplicates and trims normalized evidence, then makes exactly one DeepSeek Responses
  API JSON Schema call for a typed `FastStartPlan`. The plan may describe open research facets and
  up to three background queries with operational search intent. It has a 15-second hard deadline
  and returns a safe anchor-only narration fallback without retrying when the deadline or
  validation fails.
- The background path is independently cancellable. It consumes the FastStart research plan,
  deduplicates against fast queries, routes `DISCOVERY` to Exa and `RESEARCH`/`EXACT` to Tavily,
  and adds at most one Exa and two Tavily queries. It then invokes a separate Curator and Writer
  over typed models to produce a broader `ProgramSkeleton` and one future `NarrationScript`. It
  never owns Episode lifecycle or spending decisions.
- Search normalization produces `Evidence` only. Generic Exa/Tavily webpage results do not become
  `TrackCandidate` records by title parsing. Candidate and taste inference belongs downstream to
  the FastStart planner and Curator; a future provider that returns explicit track entities or
  MusicProvider metadata may create candidates at that boundary.

DeepSeek exposes provider-neutral `InferenceProfile.FAST`, `BALANCED`, and `DEEP` policies. FAST
uses Responses JSON Schema, disables thinking with the documented `reasoning.effort=none`, bounds
output and attempts to one physical call. BALANCED and DEEP retain bounded background behavior and
may use low/high reasoning effort. Existing Chat JSON mode remains available for compatibility.

Planning state is held separately from the persisted audio timeline. `PlanningSession` keeps
committed chapters immutable and permits background work to replace only speculative chapters.
Usage events carry stage metadata, and `GenerationTrace` derives TTFS from monotonic events. No
raw provider payload or reasoning text is persisted.

## Alternatives considered

- Sequential Research LLM → Curator LLM → Writer LLM before the first narration: rejected because
  it violates the TTFS budget and unnecessarily blocks playback.
- Let an LLM decide lifecycle, cancellation, or spend: rejected because those are deterministic
  runtime responsibilities.
- Add a queue or general agent framework: deferred; inline async orchestration is sufficient for
  the bounded Phase 3 evaluation.
- Treat search results as recommendations: rejected; generic search produces evidence only, while
  FastStart and Curator infer candidates from that evidence and own sequencing.

## Consequences

The first script can be delivered with partial or no research while background work improves the
arc. Fast-path fallback is intentionally modest and factual-safe. TTFS is observable without
claiming TTFA. The pipeline is not yet connected to EpisodeOrchestrator and does not generate TTS;
the next milestone introduces provider-neutral real music assets and deterministic radio-script
composition; TTS remains a later milestone and will convert script blocks into AUDIO_READY
narration segments.
