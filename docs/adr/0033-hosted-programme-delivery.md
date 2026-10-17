# ADR 0033: Deliver researched discussions before closing a hosted programme

Status: accepted for integration testing, 2026-10-17. Production release awaits listening.

## Context

Test episode `51a4e2b8-4e85-4056-8001-43771256786f` completed with seven songs and
only 21 seconds of single-host speech. Track research worked, but FULL generation
encountered a chapter already being authored, stopped authoring and closed its
unfinished seams. A valid 61-second dialogue arrived after materialization and
could no longer enter the immutable programme. The station's hash-based 50%
ceiling also offered no minimum discussion coverage.

## Decision

- FULL generation joins existing Writer/TTS work through its repository save.
  Progressive callers still yield to music. Claims are released after failure or
  cancellation; cancellation during a repository thread waits for that save.
  The fast opening shares the chapter authoring claim. Story reconciliation does
  not release another in-flight Writer's reservations.
- New FULL-hosting Portrait/Lineage sessions persist a small discussion plan:
  about 30 minutes plans three, with a delivery minimum of two; 60 minutes plans
  five, minimum four. Select existing eligible seams by cumulative music time,
  excluding the already-owned fast opening and final sign-off. Reserve narration
  time before fitting music. Lighter modes/stations and old sessions keep their
  existing policy.
- Leave other gaps music-only. Where capacity permits, hold one later seam as a
  backup until the primary scripts and their voicing have settled. If the actual
  delivered count is below minimum, attempt that seam once, then close normally.
  Never revive a skipped/exposed seam or change published audio. Delay authoring
  the closing until this decision so its context stays chronological.
- Count audio-ready, evidence-backed discussions with both speakers and at least
  three turns, including a substantive dialogue opening. Drafts, single-host
  fallbacks, plain announcements and sign-offs do not count. No minimum spoken
  length or new quality-scoring model is introduced. Coverage is exposed as
  `hosting_coverage` and logged on completion; failure remains playable with an
  explicit shortfall rather than endless generation.
- Pass the existing proposal intention to Curator and each dialogue's chapter
  goal to Writer. Reuse FastStart evidence for the first inter-track opening;
  if it failed, the next available discussion takes up the opening task. Prior
  text contains only earlier passages, never a later closing.
- Proposal drafts declare whether arbitrary same-artist opening fallback is
  appropriate. Narrow musical angles use ranked exact candidates; if all fail,
  reject the proposal rather than silently substituting unrelated same-artist
  music. Broad/legacy proposals retain the previous fallback. This checks identity
  and adherence to the proposed choices, not the audio's genre automatically.

## Alternatives and consequences

Prompt-only minimums do not fix lost in-flight work or count actual audio.
Mandatory long scripts, a new review agent, translation pipeline, generalized
scheduler or extra retry loop would add cost/complexity without addressing the
observed race. Reuse existing chapters, authoring markers, story artifacts and
voicing paths instead. Provider failure can still miss the minimum; one backup
is a bounded recovery opportunity, not a guarantee. Old frozen programmes are
unchanged. Live prose, first-song fit and voice pacing require a new listening
acceptance run; offline tests do not establish those qualities.
