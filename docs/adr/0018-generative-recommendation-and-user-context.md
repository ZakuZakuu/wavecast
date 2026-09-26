# ADR 0018: Generative recommendation and user context

## Status

Accepted for the Phase 8C MVP foundation.

## Context

WaveCast's ProgramProposal boundary already answers how one listener intent is
turned into a cheap, playable program promise. It is not the same problem as
deciding which program should exist for a listener. Personalization needs a small,
durable, privacy-bounded context foundation before a later recommendation planner
can use it.

This is a hackathon MVP. It does not need a research-grade recommender or a
learned user model.

## Decision

Keep recommendation and proposal construction separate:

- Recommendation answers: "What program should exist for this user?"
- Proposal generation answers: "How should this program be constructed?"

The intended flow is:

```text
User Context
    |
    v
Recommendation Planner
    |
    v
Program Ideas
    |
    v
Proposal Generator
    |
    v
Program Inventory
    |
    v
Home Feed
```

The MVP user context is limited to durable, user-owned preference data and a
small set of product-relevant behavior events:

- preference genres, optional artists, moods, optional contexts, and a
  safe-to-adventurous discovery level;
- PLAY_START, PLAY_COMPLETE, LIKE, FAVORITE, SAVE, and SKIP events;
- the user identity is derived from the verified authenticated principal, never
  accepted from the request body;
- guest access and the local guest library do not depend on account conversion;
- onboarding is optional, skippable, and completed at most once unless the user
  explicitly resets their preferences.

Events contain only event type, optional program/episode identity, owner, and
timestamp. Do not collect raw prompts, model responses, reasoning, or provider
metadata in this foundation.

Initial recommendation inputs should be explainable and may use onboarding
preferences, listening history, favorites, and recent behavior with simple
heuristic ranking. Phase 8C.1 establishes storage and API seams only; it does not
implement a planner or rank the Home feed.

Future work may consider embeddings, web trends, music news, or deeper LLM-based
user modeling after the heuristic product loop is evaluated.

## Alternatives considered

- Merge recommendation planning into ProgramProposalGenerator: rejected because
  it couples "what to make" with "how to construct it" and makes later feed
  planning harder to reason about.
- Start with embeddings or ML ranking: rejected as disproportionate before the
  product has enough behavioral data and evaluation.
- Make onboarding mandatory or require account conversion: rejected because
  guest access is an existing product invariant.
- Store arbitrary analytics payloads: rejected because this is a product-context
  seam, not a general analytics pipeline, and the extra fields create avoidable
  privacy and ownership risk.

## Consequences

- Future planners can consume stable, typed context without changing the
  proposal-generator contract.
- Preference ownership is durable and authenticated; guest behavior is unchanged.
- The event vocabulary is intentionally small and can be extended through a
  separate reviewed decision.
- Program inventory generation, recommendation ranking, background jobs, and
  trend/research inputs remain later milestones.

## Phase 8C.2 MVP implementation notes

The first planner is deterministic and explainable. It consumes a private,
authenticated user's bounded preference and behavior context and persists
owner-scoped `ProgramIdea` records; it does not invoke an LLM or populate the
Home feed. A refresh endpoint is authenticated and cooldown-bounded with a
per-user transaction lock so concurrent refreshes share one cooldown window.
Only the latest 30 ideas per user are retained; the existing AVAILABLE,
DISMISSED, and USED status vocabulary remains the lifecycle seam without adding
inventory or status-transition APIs in this milestone. The recommendation API
returns only public idea fields and never exposes the aggregated context or its
owner id.

Event identifiers are treated as optional opaque references in this MVP. Only
signals that can be resolved through an owner-scoped proposal lookup or a
public static program lookup contribute program metadata to context; unknown
references are ignored rather than granting access or creating records.


## Phase 8C.3 MVP inventory and commit-point notes

For the hackathon MVP, persisted `ProgramIdea` records are the recommendation
inventory instead of introducing a second inventory table or a background worker.

- `AVAILABLE` ideas are eligible for Home.
- Clicking a personalized card is the commit point: the idea is atomically
  claimed as `USED`, adapted through `ProgramIdeaProposalSeed`, then sent
  through the existing proposal generator, quota, ownership, and Library paths.
- Failed proposal generation restores the idea to `AVAILABLE`.
- Home inventory reads may opportunistically refill with the deterministic
  planner when recent stock has been consumed below the low-water mark. Merely
  having a small fresh initial batch does not trigger repeated refill.
- Home loading itself never calls the proposal provider. Paid/live work can only
  begin after an explicit listener click.
- Guest Home remains the shared editorial/static feed; personalized inventory is
  authenticated and owner-scoped.

This synchronous deterministic refill is intentionally an MVP seam. If the
recommendation planner later becomes provider-backed, trend-aware, or expensive,
inventory creation should move behind a durable background/scheduled mechanism
without changing the Home or proposal commit-point contracts.
