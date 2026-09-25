# ADR 0017: Account Library ownership and generation quotas

## Context

Phase 8B.1 established optional verified account identity without changing the
Phase 7 listener identity. The product now needs cloud Library state, safe
guest-to-account migration, cross-device access to already-started episodes,
and server-side protection against unlimited guest proposal generation.

Better Auth owns authentication/session storage. WaveCast owns its program,
episode, Library, and quota domain data.

## Decision

### Identity and ownership

- AuthPrincipal.listener_id remains the immutable browser/runtime identity.
  Verified user_id is an additive account identity; the API never derives it
  from request JSON or an unverified client field.
- Durable episodes may have nullable owner_user_id, stored as a first-class
  column outside the public episode payload.
- API episode access is allowed to the original listener or to the matching
  verified account owner. Account ownership does not rewrite listener_id,
  committed timeline, or runtime state.
- A guest episode can be claimed only when its durable listener_id exactly
  matches the authenticated request's listener. Client-supplied episode IDs
  alone never establish ownership.
- Account-owned episodes are found by (owner_user_id, seed_id) before a new
  episode is created, allowing another device on the same account to resume the
  original episode.
- Proposal ownership is claimed by the same exact-listener rule. A conflicting
  proposal ID is never allowed to overwrite its prior owner or content.

### Cloud Library

- WaveCast persists account Library records in its own
  user_library_entries table; it does not couple product data to Better Auth's
  internal schema.
- /api/me/* requires a verified account and returns 401 for guests.
- A first authenticated device merges its existing guest local snapshot before
  reading canonical account state. Merge is idempotent: favorites and created
  IDs use union; recents use newest updatedAt; saved episodes use newest
  savedAt.
- The local guest snapshot is retained. A user-scoped marker records successful
  initial merge so stale guest state cannot resurrect items removed later from
  the cloud Library. Each signed-in account has an isolated local cache.
- The service validates every merged proposal/episode against server ownership
  and canonical episode metadata before accepting it.

### Generation quotas

- Dynamic proposal creation reserves capacity before invoking a generator.
  Reservations count against concurrent quota checks.
- A successful distinct persisted program_id is the idempotent charge
  identity. Provider/contract failures and unsuccessful persistence release
  the reservation; retrying or resuming an existing program does not charge
  that program again.
- Pending reservations expire after 15 minutes. Each reservation attempt
  releases expired pending rows before counting capacity, recovering quota
  after a process crash without an unbounded background cleanup job.
- Default limits are three guest programs per listener lifetime, twenty per
  account per UTC day, and one hundred globally per UTC day. The account/global
  limits are operationally configurable. Static/demo playback and browsing do
  not consume proposal quota.
- PostgreSQL advisory transaction locks serialize the relevant quota checks;
  the in-memory implementation preserves the same semantics for mock mode.

## Consequences

- Account Library and episode access survive API process reconstruction when
  PostgreSQL is configured; guest runtime behavior remains available without
  authentication.
- Listener-scoped phase 7 playback semantics remain intact while account
  owners can resume the same episode cross-device.
- Quota checks are server-side and occur before proposal provider work, so
  clearing browser storage or issuing parallel requests cannot bypass the
  configured cap.
- This phase does not add account TasteProfile, For You ranking, provider calls,
  deployment changes, or multi-device realtime playback coordination.
