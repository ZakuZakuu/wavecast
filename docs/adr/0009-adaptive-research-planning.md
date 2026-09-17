# ADR 0009: Let FastStart plan topic-adaptive background research

## Context

The first progressive-intelligence implementation assumed every request was a
music-discovery request and spent background queries on fixed similarity,
bridge, and cross-scene templates. That made a career question, a creative
process question, and a history question share the same research shape. It
also made the background stage depend on an exact three-query list.

## Decision

FastStart remains one bounded structured call, but its typed result now carries
an optional `ResearchPlan` containing:

- a central question;
- open-ended `ResearchFacet` records with stable IDs, questions, priorities,
  and source preferences;
- up to eight `PlannedResearchQuery` records with operational `SearchIntent`
  (`DISCOVERY`, `RESEARCH`, or `EXACT`), facet IDs, and rationale.

The deterministic search stages own the budget and routing. Fast research still
runs exactly one Exa and one Tavily query. Background research consumes the
FastStart plan, deduplicates against those fast queries, routes discovery to
Exa and research/exact to Tavily, and executes no more than one Exa plus two Tavily
queries (three total). Plans with zero to eight proposed queries are valid; provider
failures and cancellation remain isolated and do not trigger retries.

When FastStart is unavailable, the application creates a generic topic-based
fallback plan rather than a similarity template. Search normalization creates
`Evidence` with safe source title, facet, and intent metadata. A webpage title
is never promoted to a `TrackProposal`; candidate inference remains in
FastStart/Curator or a future explicit music-catalog boundary.

Curator receives the plan and adapts the narrative to the actual topic. Its
existing typed chapter and monotonic novelty invariants remain unchanged.
Trace and the opt-in episode probe expose only plan metadata (central question,
facet summaries, and planned query text); provider payloads, prompts, and
credentials remain outside diagnostics.

## Alternatives considered

- Add a classifier before FastStart: rejected; it adds a round trip and turns
  open-ended user requests into a brittle fixed taxonomy.
- Keep fixed similarity query templates: rejected; they do not answer
  non-discovery requests and encourage unsupported editorial assumptions.
- Add a queue or workflow engine: deferred; the existing inline cancellable
  service is sufficient for the bounded Phase 4.6 milestone.
- Let search results become track candidates: rejected; generic web evidence
  must still cross the deterministic proposal-to-catalog boundary.

## Consequences

Research intent is now observable and reusable without changing Episode
runtime, browser playback, provider contracts, or live budgets. The background
stage may intentionally do less work when the plan has fewer useful facets or
queries. Future providers can honor facet source preferences without changing
the orchestration seam.

## Phase 4.8.2 extension: research quality and provenance

Background research now has a narrow `BackgroundResearchPlanner` seam. When
the FastStart path falls back, it may make one bounded structured planning call
after first-script readiness; a planner failure deterministically uses the
generic topic plan. The planner is cancellable and never performs browsing.
FastStart plans that already contain a useful plan continue directly to
background execution. The application still selects no more than one Exa and
two Tavily queries from the small proposal pool.

Search normalization canonicalizes URLs before deduplication and evidence-ID
generation. `Evidence` records conservative source provenance metadata and
source preferences only influence deterministic ordering/prioritization; they
are not authority scores. Search results remain evidence, not track entities.
Curator and Writer contracts may attach typed claim-support records for facts,
correlations, causal claims, editorial interpretation, and uncertainty. Each
record must cite non-empty evidence IDs within the chapter's scoped evidence.

The live probe's successful report exposes the selected research plan,
provenance summaries, program-skeleton metadata, usage by stage, and safe
provider event summaries. Prompts, provider payloads, reasoning text,
credentials, and signed URLs remain excluded.
