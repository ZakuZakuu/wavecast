# AGENTS.md

## Mission

Build and maintain an AI-native music radio / guided-listening product for a music hackathon. The product generates high-quality, research-grounded, personalized music programs on demand, while hiding generation latency behind immediate music playback.

The product is **not** a generic chatbot, playlist generator, or one-shot podcast generator. Its core is a deterministic streaming episode runtime with bounded AI agents inside it.

Your default behavior should be highly autonomous: inspect the repo, infer the next sensible implementation step from the current milestone and docs, implement it, test it, commit it, and continue. Do not stop for routine engineering decisions.

## Preliminary-round priority gate

**Before making any non-trivial change during the current hackathon preliminary stage, read `docs/PRELIMINARY_PRODUCT_TARGET.md`.**

The current delivery order is intentionally narrow:

> **Listening P0 -> UI P0 -> preliminary-round submission**

Do not let historical architecture work, old ADRs, or implementation neatness expand this scope by default.

For this milestone, prefer:

1. a convincing listener-facing radio experience;
2. uninterrupted playback and graceful degradation;
3. natural narration/music arrangement;
4. demo reliability and visible polish;
5. only then broader architecture generality.

In particular:

- narration is **not** restricted to gaps between complete songs;
- a temporary two-track or short generated prefix is **not automatically a complete programme**;
- there is **no product requirement to hard-code a minimum song count** for a programme;
- the preliminary P0 focuses on one polished, lightly hosted radio style rather than perfect parity across NONE/LIGHT/FULL;
- avoid another broad player/runtime rewrite unless a concrete blocker makes it unavoidable;
- if an existing implementation invariant conflicts with the current product target, do not silently optimize the invariant. Reconcile the conflict against the product target first.

Positioning (see `docs/PRELIMINARY_PRODUCT_TARGET.md` section 0): the differentiator is niche, personalised programmes that would not otherwise exist, not out-doing human hosts or other radio/podcast apps. The music is real; AI researches, selects, writes and narrates. Do not market or optimise the product as "AI beats human radio", and do not claim features that have not been verified live.

---

## Source of truth

Read these before making non-trivial changes:

1. `AGENTS.md`
2. `docs/PRELIMINARY_PRODUCT_TARGET.md` for the current user-facing product goal
   and the explicit preliminary-round scope/priority order
3. `docs/PROJECT_STATE.md` for the current milestone, branch/main state, and
   immediate next task
4. `docs/CODEX_HANDOFF.md` for the long-lived product and architecture contract
5. Any relevant ADRs under `docs/adr/`
6. Existing tests and schemas

If implementation and docs disagree, do not silently redefine the product. Preserve established domain semantics and either:

- fix the implementation if the docs are clearly authoritative, or
- add/update an ADR when a design change is genuinely justified.

After a consequential milestone, architecture, provider, or runtime change,
update `docs/PROJECT_STATE.md` so a fresh session can recover the active state
without duplicating the long-lived handoff or ADRs.

---

## Session context and scoped contributors

`docs/PROJECT_STATE.md` is the only current-state entry point. Keep it a short
snapshot, not an append-only session transcript (aim for about 8 KB or less).
Move superseded execution history to `docs/history/`; keep deployment procedures
in `docs/deployment/`, design sources in `docs/design/`, and submission copy/assets
in `docs/submission/`. Do not create a competing `CURRENT_STATUS.md`.

Codex owns cross-project planning, verified context, and canonical state updates.
Claude is a scoped contributor: give it the task goal, exact relevant files/assets,
constraints, acceptance criteria, and expected deliverables. It reports changes,
checks and unresolved gaps rather than re-summarising all project history.

A scoped contributor reads AGENTS, the preliminary product target and the short
current state, then only the relevant sections of handoffs/ADRs/tests. The broad
reading list above applies when choosing cross-project or architecture work;
it does not require an isolated poster/UI task to ingest every historical note.
Source-of-truth and runtime invariants still apply. If its task exposes an API or
architecture decision, hand that decision back to the owner rather than silently
expanding scope. Short task packets may be delivered in conversation; do not
create a new permanent handoff file for every small assignment.

---

## Autonomy rules

Proceed without asking for confirmation when the decision is reversible and does not change product semantics. Examples: file organization, internal helper APIs, naming, test structure, lint configuration, retry implementation, mock data, small dependency choices, refactors, and standard UI implementation details.

Stop and ask only when one of these is true:

- a required secret/credential is unavailable and no mock/fallback can unblock development;
- a destructive or irreversible action is required;
- two materially different product behaviors are both plausible and the docs do not resolve them;
- the requested action could make a private repository or private user data public;
- a core architectural invariant would need to change.

When blocked by a missing external API key, **do not stop the project**. Implement the provider interface, mock provider, tests, configuration, and integration seam so the real credential can be inserted later.

---

## Non-negotiable architecture invariants

### 1. Deterministic orchestration, bounded intelligence

`EpisodeOrchestrator` and episode lifecycle logic are ordinary deterministic application code. LLMs must not decide whether to keep spending, whether an episode is committed, whether the user has left, whether a job should be cancelled, or what lifecycle state to enter.

AI agents may research, curate, plan, write, and re-plan only within explicit schemas and budgets.

### 2. Agent roles stay separate

Keep at least these logical roles separate even if they temporarily use the same model/provider:

- Research Agent
- Curator Agent
- Writer / Showrunner Agent
- Replanner

Do not create a single unconstrained "super agent" that searches, selects music, writes scripts, generates TTS, and mutates runtime state by itself.

### 3. Provider abstraction is mandatory

Business logic must depend on interfaces, not vendor SDKs. Maintain clean abstractions for at least:

- `LLMProvider`
- `SearchProvider`
- `TTSProvider`
- `MusicProvider`
- `AudioAnalysisProvider`
- `ObjectStorageProvider` when appropriate
- `CoverRenderer`

Vendor-specific details belong under provider adapters.

### 4. Past is stable; future is mutable

Episode content already exposed to the user is immutable from the user's perspective.

Maintain the distinction between:

- **Committed frontier**: content already played or made seekable to the user; never rewrite it.
- **Generated/audio-ready frontier**: materialized content that may be seekable depending on state.
- **Speculative frontier**: future plan/script candidates that may be discarded or re-planned.

Replanning may only modify uncommitted future content.

### 5. Generate just ahead of playback

Do not materialize a full episode by default. Maintain a small playback buffer, approximately two chapters / five to eight minutes ahead, unless the user explicitly requests full materialization.

The first song should be known before the expensive pipeline starts whenever possible so playback can begin immediately.

### 6. Full generation is an explicit mode

A user may explicitly request the full episode to be generated. Published/shared episodes must be fully materialized and frozen.

### 7. No loading wall when avoidable

If a next narration segment is not ready but the next planned track is available, prefer playing music immediately and continue generating narration in the background. Do not insert unnecessary "please wait while AI generates" screens into the listening flow.

---

## Current stack

Treat these as defaults, not hardcoded assumptions:

### Frontend

- Next.js
- React
- TypeScript
- Zustand for client playback/UI state
- Web Audio API and/or controlled audio elements for playback orchestration
- Programmatic SVG covers for MVP

### Backend

- Python
- FastAPI
- Pydantic / PydanticAI for structured agent IO and thin agent runtime
- Postgres (Supabase-compatible is fine)
- Redis for queue/cancellation/ephemeral coordination/pub-sub where useful
- S3-compatible object storage for generated narration audio

### AI / search providers

- DeepSeek V4.1 Flash as initial model for Research, Curator, Writer, and Replanner
- Exa Auto for semantic music discovery
- Tavily for web research/evidence extraction
- Serper as optional exact-search fallback
- MusicBrainz for canonical music entities/metadata
- Last.fm for similar-track/artist/tag signals
- MiniMax Speech 2.8 HD for TTS
- Ocean Listen as optional/offline audio-analysis enhancement, never a hard runtime dependency

### Music playback

Implement behind `MusicProvider`. The hackathon MVP may use a mock/local/test source. The intended final integration is a TME/QQ Music provider if/when official APIs become available.

---

## Domain expectations

Core domain concepts should be explicit, typed, persisted where appropriate, and testable:

- `EpisodeSeed`
- `LiveEpisode`
- `MaterializedEpisode`
- `ProgramSkeleton`
- `ChapterPlan`
- `Segment`
- `MusicSegment`
- `NarrationSegment`
- `ResearchBundle`
- `Evidence`
- `TrackCandidate`
- `UserTasteProfile` or equivalent lightweight session taste representation
- frontier/cursor state

Suggested episode states:

`SEED -> STARTED -> RESEARCHING -> PLANNED -> STREAMING -> MATERIALIZING -> MATERIALIZED -> PUBLISHED`

Suggested segment states:

`PLANNED -> SCRIPT_READY -> AUDIO_GENERATING -> AUDIO_READY -> COMMITTED -> PLAYED`

Exact enum names may evolve, but semantics must remain clear.

---

## Agent contracts

Agent outputs must be structured Pydantic models. Avoid free-form Markdown as the primary machine interface.

### Research Agent

May use search/metadata tools. It should produce evidence-backed hypotheses and candidate tracks. Enforce bounded search budgets such as maximum rounds, maximum queries, timeout, and estimated cost.

### Curator Agent

Consumes research, user taste signals, music availability, and optional audio features. It should not casually browse the web. It chooses a coherent path through candidates and assigns narrative roles such as anchor, validation, bridge, contrast, discovery, or resolution.

### Writer / Showrunner

Prefer a tool-free, near-pure transformation from chapter context + evidence + prior committed transcript into narration text and TTS cues. It must not invent unsupported factual claims or swap tracks unilaterally.

### Replanner

Consumes the current future skeleton plus user feedback such as skip, like, "less talking", or "explain more" and returns a bounded patch to uncommitted chapters.

---

## UX/runtime behavior to preserve

- Home cards are cheap "program promises", not fully generated episodes.
- A card should include at minimum title/topic, estimated duration, procedural cover parameters, and opening track information when possible.
- Clicking a card should begin the opening track immediately or as close to immediately as platform constraints allow.
- The opening experience should have enough editorial context prepared that a short host introduction can arrive during an appropriate early instrumental/non-vocal window; it does not need to wait for the first song to finish.
- Narration may be arranged inside a track, over an intro/break/outro, or around a transition. Do not model narration as inherently inter-track-only.
- Expensive research, writing, and TTS may continue after the click, but the listener should perceive a continuous programme rather than generation stages.
- Users may seek backward through generated/committed content.
- Users may not seek beyond the generated frontier.
- "Next" should skip to the next chapter/track; it must not block on unfinished narration if playable music is already known.
- Repeated skips are meaningful preference signals and may trigger replanning of speculative content.
- Exiting pauses/stops future generation as soon as practical; already completed artifacts may remain cached.
- Re-entering an episode should resume from persisted state.
- Full generation/materialization is user-triggerable.
- Only fully materialized episodes may be published/shared in the MVP architecture.

---

## Frontend policy

For the first vertical slice, prioritize information architecture, responsiveness, playback correctness, and visible generation state over visual polish.

Do not spend disproportionate time on decorative animation before the core listening loop works.

MVP pages may be limited to:

- Home
- Episode Player
- Saved/Library

The final visual system will be refined later. Keep the component system clean enough to redesign without rewriting application logic.

---

## Testing policy

New non-trivial behavior requires tests.

At minimum maintain:

- unit tests for episode/segment state transitions;
- tests for frontier invariants;
- tests for cancellation and resume behavior;
- tests for provider adapters using mocks/fakes;
- structured-output validation tests for agent contracts;
- integration tests for the core vertical slice;
- frontend tests for seek/next/generated-frontier behavior where practical.

Critical invariants to test explicitly:

- committed segments never change after replanning;
- users cannot seek past the generated frontier;
- cancelling an episode prevents creation of new speculative work;
- "full materialize" reaches a fixed materialized episode;
- missing external credentials do not break mock-mode development;
- provider failures degrade gracefully and do not corrupt episode state.

Run lint, type checks, tests, and production builds before declaring a milestone complete.

---

## Git and PR discipline

The repository is private and must remain private.

Use small, coherent commits with meaningful messages. For substantial work, create a feature branch and PR rather than pushing directly to `main`.

Prefer PRs for anything touching:

- domain schemas;
- orchestration/state machine;
- agents;
- providers;
- database migrations;
- player behavior;
- API contracts;
- infrastructure.

Direct-to-main changes should be limited to truly trivial edits such as typos or similarly low-risk maintenance, and only if repository policy permits it.

Before opening a PR:

1. Run formatting/linting.
2. Run backend and frontend type checks.
3. Run relevant test suites.
4. Run production builds where applicable.
5. Summarize architecture impact and known limitations.
6. Call out follow-up work explicitly.

Never rewrite shared Git history or force-push unless explicitly authorized.

If no GitHub remote exists but `gh` is authenticated and repository creation is authorized by the task, create a **private** repository. Never create a public repository by default.

---

## Documentation discipline

Keep docs current with implementation.

For consequential design changes, add an ADR under `docs/adr/` describing:

- context;
- decision;
- alternatives considered;
- consequences.

Do not create excessive documentation for trivial implementation details.

---

## Cost discipline

This project is self-funded. Avoid unnecessary paid calls in development.

- Default automated tests to mocks/fakes.
- Never call paid APIs from ordinary unit tests.
- Cache generated narration and research artifacts where sensible.
- Track provider usage/cost metadata so real usage can be measured later.
- Keep research loops bounded.
- Do not pre-generate expensive content for unclicked home cards.

---

## Security and secrets

- Never commit API keys, tokens, cookies, or credentials.
- Use `.env.example` with names only.
- Keep generated private user data out of logs where possible.
- Sanitize provider errors before returning them to clients.
- Do not change repository visibility without explicit user approval. Never expose credentials, private user data, or deployment secrets.

---

## Definition of done for a milestone

A milestone is not done merely because code was written. It is done when:

- the intended user flow works end-to-end;
- tests cover critical behavior;
- lint/typecheck/build pass;
- docs/ADRs are updated if necessary;
- the work is committed cleanly;
- a PR summary explains what changed, what remains mocked, and what should be reviewed.

When uncertain, optimize for maintainability, observable state, bounded cost, and a convincing listening experience.


---

## Hosted deployment discipline

### CI selection

PR checks are selected automatically; see `docs/deployment/ci.md`. Web checks
always run. PRs limited to known Web/documentation paths skip the backend and
Docker deployment jobs. Backend/shared/deployment/unknown paths, release PRs
targeting `main`, pushes to `main`, and manual CI runs get full validation.
Do not bypass CI with commit-message skip directives or workflow path filters.
Use a manual CI run when a full-stack checkpoint is needed on a feature branch.

### Hosted checkpoints

WaveCast has constrained hosted deployment budgets. Treat deployments as explicit
human-test checkpoints, not as a side effect of every code commit.

- `main` is the release branch. Do not advance or deploy it for routine iteration.
- `integration` is the single hosted integration branch used when a human needs
  to test the current frontend/backend together.
- During implementation, prefer local commits without pushing. When GitHub-side
  editing is required, detached commits are acceptable; advance `integration`
  only when a coherent testable checkpoint is ready.
- Batch related fixes into one `integration` update. Do not push one hosted
  deployment per small edit.
- Vercel should deploy only `main` and `integration`, and should ignore commits
  that do not affect the Web app or its root workspace dependencies.
- During active hackathon development, the Railway API service may track
  `integration` so one `integration` update deploys the matching backend
  without Railway Agent. Before a public release, switch Railway back to `main`
  and deploy the accepted release SHA.
- Do not use Railway Agent for routine logs, metrics, variables, health checks, or
  redeploys. Reserve it for operations that cannot be expressed with ordinary
  Railway APIs/CLI.
- A hosted checkpoint is complete only after the relevant deployment reaches a
  successful state and its health/build signal is observed. Never claim tests
  passed unless their output was actually observed.
