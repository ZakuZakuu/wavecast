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
- up to three `PlannedResearchQuery` records with operational `SearchIntent`
  (`DISCOVERY`, `RESEARCH`, or `EXACT`), facet IDs, and rationale.

The deterministic search stages own the budget and routing. Fast research still
runs exactly one Exa and one Tavily query. Background research consumes the
FastStart plan, deduplicates against those fast queries, routes discovery to
Exa and research/exact to Tavily, and runs no more than one Exa plus two Tavily
queries. Plans with zero, one, two, or three usable queries are valid; provider
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
