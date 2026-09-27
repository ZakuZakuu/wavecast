# WaveCast Project State

**Last updated:** 2026-09-27

## Product reminder

WaveCast is an AI-native guided-listening radio product: a listener starts a
program immediately, while bounded research, curation, writing, and narration
materialize a coherent episode just ahead of playback. It is a deterministic
streaming runtime with bounded intelligence, not a chatbot or a static playlist.

## Current milestone and main state

- **Current milestone:** Streaming Runtime v2 architecture and implementation after hosted live-listening validation exposed generation/playback coupling.
- **Canonical base for capability wiring:** `b0937c835af470c3a86ee5540f8265c1efcd7f6a` (PR #82 merge commit).
- **Hosted proof so far:** Better Auth/user context, DeepSeek recommendation inventory, Postgres persistence, Recommendation -> Program Proposal, and Program Detail are live in production. PR #81 removed the Postgres async-facade 500; PR #82 preserves the recommendation's editorial identity across Program Proposal materialization and hides unresolved mock artist metadata.
- **Provider activation contract:** keep `WAVECAST_PROVIDER_MODE=mock` as the production safety default and activate proposal, music, fast-start, research, curator, writer, and TTS with capability-level selectors. Deploying the wiring alone must not create new paid calls.
- **Narration default for the live rollout:** MiniMax `speech-2.8-turbo`, baseline speed `0.8`, with environment overrides retained.
- **Phase 8B.2:** cloud Library, account episode/proposal ownership, guest/account/global generation quotas, and durable quota reservation expiry are merged after the #75 stack repair. The current Alembic chain is `0003_user_context -> 0004_program_ideas -> 0005_cloud_library_quota -> 0006_quota_reservation_expiry`.
- **Phase 8C:** optional authenticated onboarding/preferences, bounded product events, explainable private UserContext, owner-scoped durable recommendation inventory, low-water refill, and authenticated For You Home are merged. The current hardening branch adds an independently gated DeepSeek recommendation planner with deterministic provider-failure fallback; production remains deterministic until `WAVECAST_RECOMMENDATION_PLANNER=deepseek` is explicitly configured.
- **Recommendation commit point:** Home inventory reads do not call paid/live proposal providers. Clicking a personalized recommendation atomically consumes the idea and reuses the existing proposal generator, quota, ownership, CREATED Library, Program detail, Episode, and Player paths. Failed generation restores the recommendation.
- **Release smoke at `a8784bb...`:** Ruff/mypy passed; backend pytest 440 passed / 20 skipped; Web lint/typecheck/build passed with 59 Vitest tests; isolated Postgres targets 17 passed; Alembic upgraded through `0006`; credential-free deployment smoke and Guest browser product smoke passed. A Docker Hub auth timeout prevented a separate Compose image pull, but did not indicate an application failure.
- **Immediate work:** implement [ADR 0020](adr/0020-buffered-streaming-runtime-v2.md). Hosted live listening proved the browser-owned transport after PR #88, but also exposed that browser-driven inline generation, mock-derived 30-second timing, atomic chapter readiness, and fail-closed track/TTS behavior cannot meet the intended radio experience. Replace those runtime assumptions before reopening embeddings, ML ranking, vector search, trend/news ingestion, lyrics intelligence, or other secondary work.
- **Privacy and cost gate:** recommendation context remains internal and owner-scoped; the recommendation prompt excludes user IDs and API responses omit private context and ownership identifiers. AI recommendation generation is inventory-based rather than per-Home-load and remains off by default. Other live/paid provider calls remain explicit commit-point actions and are never performed by ordinary CI or Home loading.

## Streaming Runtime v2 decision

ADR 0020 is the current implementation contract for live generation. It
preserves the durable Episode, CAS persistence, ProgressiveAssemblySession,
catalog trust boundary, SSE, browser-owned playback clock, and deterministic
MixPlan direction, while superseding these Phase 7A implementation assumptions:

- the browser periodically owns generation through `ensure-buffer`;
- expensive provider work is request-owned inline work;
- a chapter must become atomically AUDIO_READY before any of its playable music
  can help continuity;
- a mock-derived 30-second duration may act as a production playback boundary.

The v2 target is a durable backend Generation Coordinator with a ready queue,
graceful degradation, progressive/full convergence on one Episode identity, and
declarative DJ arrangement layered on the stable browser transport.

### Runtime v2 implementation progress

- PR #102 separates **playable readiness** from the contiguous seek frontier.
  `generated_frontier_seconds` remains the browser seek boundary, while
  `ready_audio_seconds_ahead` and `has_ready_successor` describe whether
  playback can continue through optional narration gaps. Browser completion may
  skip unfinished narration only when another ready source is already available.
- The current Slice C work removes **Writer and TTS from the
  music-readiness critical path**. Staged generation persists verified
  AUDIO_READY music first. The durable worker then authors optional narration
  only for still-speculative chapters, persists it as SCRIPT_READY, and performs
  TTS as a second best-effort enrichment. Late Writer/TTS results are discarded
  once the chapter is exposed, and completed Writer attempts are recorded in the
  durable progressive session to prevent blind paid retries.
- Speculative narrative-only or unresolved route beats cannot hold the music
  ready queue in front of a later playable track. Continuity generation advances
  past them while preserving exact resolved music identity.
- One major coupling point intentionally remains after this slice: initial
  `ProgressiveAssemblySession` preparation still runs the broader
  research/curation/resolution path before the first staged successor exists.
  That is the next continuity target before Arrangement/DJ v2.
- The legacy Web `MixEngine` is not the active EpisodePlayer transport and must
  not be revived as a synthetic playback clock. Arrangement/DJ v2 remains
  deferred until continuity no longer depends on slow narration/intelligence
  stages.

## Phase 7A progressive generation contract

Phase 7A changes the runtime from a static preloaded future to bounded
on-demand chapter generation. A new episode persists only its committed opening
track and remains immediately playable; starting the episode performs zero
generator calls. The async scheduler serializes generation per episode and
coalesces concurrent buffer requests.

Each generated chapter must contain playback-ready music before the orchestrator
appends it. Optional narration may remain absent or SCRIPT_READY and is enriched
later without blocking the ready music queue. Append validation remains atomic
for music identity/readiness and preserves the ready/committed prefix. Heartbeats are allowed during provider work because the append check
uses a structural last-segment anchor rather than a raw version; if the
listener leaves, the generated result is discarded and resume can request the
next missing chapter. The deterministic generator derives its next chapter from
the persisted timeline rather than process-local cursor state, so leave/resume
and generator reconstruction cannot skip a chapter. Full materialization drains
the same deterministic, credential-free fake generator and freezes the episode.
No live provider, external queue, Redis/Celery worker, or Web contract change
is part of this slice.


## Phase 7B.1 staged intelligence session contract

The first 7B slice adds a serializable `ProgressiveAssemblySession` to the
sanitized assembly result. It captures normalized fast-start, research,
curation, resolved-route, narration-slot, and timing data without provider
clients, raw responses, credentials, or ephemeral playback URLs. Its
`next_chapter(LiveEpisode)` method derives the first missing route chapter
from persisted timeline chapter IDs; the session has no authoritative mutable
cursor. This contract is credential-free and does not replace the Phase 7A
default generator or connect live providers.

## Phase 6B.1 canonical mix-plan contract

PR #53 made MixPlan the server-owned deterministic arrangement consumed by the
Web runtime. GET /api/episodes/{episode_id}/mix-plan exposes only the
listener-owned ready prefix, and the Web player derives readiness from an
arrangement signature that refreshes when a segment moves between pending,
ready, or skipped states. This milestone added no live/provider behavior.

## Phase 6B.2 offline mixdown

PR #54 added a deterministic ffmpeg renderer that consumes the canonical
MixPlan and only already-owned WaveCast audio assets. POST
/api/episodes/{episode_id}/mixdown stores a stable MP3 artifact keyed by the
plan fingerprint; it does not call providers, change episode timing, or
mutate the timeline. Backend CI now installs and verifies ffmpeg/ffprobe before
running the renderer tests. The merged main is
405b83254b3ce14efb114b7dc8e6554a8dc6b439.

## Phase 6B.3 owned music snapshot

The current implementation adds an explicit prepare-mixdown stage: strict
same-origin classification identifies owned assets, sidecar proxies, Audius
proxies, and unsupported sources; injected snapshot fetchers persist supported
audio into deterministic local-storage keys with safe metadata; and the
listener-owned episode is updated atomically only after every required music
source succeeds. Cache hits avoid a second fetch. The existing canonical
MixPlan and mixdown endpoint remain unchanged. This is credential-free work;
real provider snapshots and live episodes are intentionally excluded.

## Phase 6B.4 production playback snapshot wiring

Phase 6B.4 extracts an in-memory ResolvedPlaybackRequest seam from the
existing sidecar and Audius playback paths. Browser proxies and
ProviderPlaybackSnapshotFetcher share this resolver, while snapshot fetching
performs one bounded full-track GET with audio content-type validation,
streaming byte limits, redirect following, and safe reason codes. Existing
segment duration is passed into the snapshot contract so the preparation step
does not re-resolve timing metadata. The default API store is now wired to this
fetcher, but tests remain credential-free and no live provider request is
performed by the development workflow.

## Phase 6B.5 thin export UX

Phase 6B.5 adds the first user-visible export path in the Web EpisodePlayer:
a MATERIALIZED episode can explicitly run prepare-mixdown, then mixdown, and
download the returned MP3 without adding a backend state machine or changing
the playback engine. The UI keeps export state and errors separate from
playback state, prevents duplicate submissions, reuses a successful artifact,
and exposes a visible fallback download link. Preparation with ready=false
never calls mixdown; artifact URLs must be WaveCast-owned
/api/assets/audio/ paths with audio/mpeg content type. This slice is
credential-free and makes no live or paid provider calls.

Known UX debt: prepare-mixdown promotes provider sources to owned URLs, so an
active player may observe one MixEngine refresh through the existing
heartbeat/SSE convergence. The export flow does not proactively pause, seek,
commit, or refresh the episode; a later human playback check should decide
whether that refresh needs a separate fix.

## Phase 5.3A radio-writing rubric

Phase 5.2 human listening accepted the track selection and editorial arc but
identified article-like Chinese phrasing, broad cultural generalizations, and a
generic outro. GPT's Phase 5.3 plan narrows the next slice to:

- public source links plus abstract corpus notes; no copied transcripts or
  host-specific imitation;
- a typed zh-CN human-review rubric covering concrete listening cues, fact to
  sound to connection, spoken pacing, cultural precision, contextual deixis,
  and outro callbacks;
- a small set of self-authored weak/strong contrast fixtures;
- credential-free tests that verify rubric completeness and language scope.

This slice deliberately does not change RadioScriptBlock, Writer prompts,
NarrationSlotContext, EpisodeAssembly, playback, TTS, overlay/ducking,
crossfade, or any live provider configuration. The corpus boundary is recorded
in docs/research/phase53-radio-writing-corpus.md; the design decision is
recorded in ADR 0013.

## Phase 5.3B Writer guidance

Phase 5.3B turns the reviewed rubric into a concise prompt guidance block that
is injected only for zh-CN. It emphasizes concrete listen-for cues, fact to
sound to connection, one editorial action per block, speakable Chinese,
cultural precision, contextual transitions, and thesis-linked outros. Empty
evidence still forbids invented musical or factual detail; en-US and ja-JP do
not receive the Chinese guidance.

This slice does not add schema fields, perform regex or deterministic prose
rewriting, or change evidence, claim-support, slot, cardinality, physical-gap,
assembly, playback, or provider behavior.

## Phase 5.3C offline writing sanity

Phase 5.3C provides a typed review artifact with self-authored weak/strong
comparisons for opening narration, direct A to B track intros, narrative-only
middle transitions, and final outros. Every example carries its real
NarrationSlotContext, including an explicit empty-evidence case. The bundle is
for human comparison only: it has no automatic quality pass/fail and is not
imported by production Writer code.

## Phase 5.2 first listening episode

The current task is to produce the first human-listenable full-track episode
from the Fang Datong Soul / R&B brief. Acceptance is editorial and musical:
selection, reasons, sequence, discovery value, and whether the program creates a
new understanding. Crossfade, transition effects, voice character, section
selection, and UI polish are explicitly deferred.

The credential-free audit found that the existing Web player already supports
play/pause, progress, current segment, continuous HTML5 audio, SSE updates,
resume, and generated-frontier seeking. The missing last mile was a formal
bridge from PlayableEpisode returned by live assembly into the listener-scoped
runtime. The current implementation adds:

- EpisodeOrchestrator.import_materialized() with MATERIALIZED/FULL lifecycle
  semantics and listener ownership preserved;
- POST /api/episodes/from-materialized;
- /episode/materialized/[episodeId], reusing the existing player;
- opt-in live-probe bundle export and a small bundle import script;
- WaveCast-owned sidecar music proxy URLs, with the current upstream URL resolved
  only at playback time and Range headers streamed through the API;
- materialized import accepts only WaveCast-owned same-origin /api/... audio
  paths and returns a safe 422 for external URLs.

The bundle contains only the playable episode contract and safe episode metadata;
it does not retain prompts, provider responses, hidden reasoning, credentials, or
signed URLs. The live target remains one case, 1,200 seconds, at most five
tracks/eight chapters, full-track playback, and max_attempts=1 with no retry.
No live provider call is part of this implementation PR.

Validation on merged PR #36: backend 283 passed, 6 skipped; backend Ruff and
mypy pass; web ESLint, TypeScript, 9 Vitest tests, and production build pass;
GitHub backend/web CI passed for review HEAD 0167ba282d8885a1f9b06a49b1998826a65e449e.

The single authorized Fang Datong live assembly completed once with the bounded
Phase 5.2 target (full-track playback, up to five tracks/eight chapters,
max_attempts=1). The resulting materialized episode was imported once into the
listener-scoped runtime and is available at:
http://127.0.0.1:3001/episode/materialized/62850b54-0ebf-4498-a423-259387892f77

Safe live summary: 5 playable music tracks and 14 narration blocks are present;
all timeline audio assets use WaveCast-owned /api/... paths; the existing Web
player successfully loaded the episode, began the opening track, and exposed
pause, next-chapter, current-item, continuous timeline, and progress controls.
The current human-review question is editorial quality, not transition effects,
crossfade, voice character, or UI polish. The imported artifact is owned by the
phase52-fang-datong listener session. No raw prompts, provider responses,
reasoning, credentials, or signed URLs are retained in this state record.

## Phase 5.3 final bounded live validation and artifact review

PR #50 added one same-stage retry only for typed Responses
status=incomplete failures that are not max_output_tokens, alongside the
existing schema-validation retry. Output-limit, empty, failed-status, generic
contract, authentication, budget, and provider-outage failures remain bounded
without this extra retry. The PR was exact-head reviewed by GPT and merged with
backend/web CI green at e42166f13ea07a6b667b49bec16fa37b092ca746.

The post-merge Phase 5.3 live run used the established Fang Datong benchmark:
full-track playback, desired duration 1,200 seconds, at most five tracks/eight
chapters, and max_attempts=1 for the assembly. It succeeded with 5/5 tracks
resolved and 4/4 transitions surviving:

1. 方大同 — 春风吹
2. 方大同 — 每天每天
3. Musiq Soulchild — Just Friends (Sunny)
4. Erykah Badu — Other Side Of The Game
5. D'Angelo — Brown Sugar

Safe materialization metadata: 1,359 seconds of music, 157 seconds of
narration, 1,516 seconds total, narration ratio 10.36%, five final timeline
narration segments, and no unresolved proposals. The 1,200-second target is
non-blocking infeasible for this run because five full tracks already exceed
the target; tracks were not shortened. The safe usage report recorded 17
provider events, five search queries, three search credits, and reported actual
cost USD 0.014.

Primary listening route:
http://127.0.0.1:3001/episode/materialized/2205b6ed-7318-4642-bf6b-35053a1e8d69

Fallback known-good route:
http://127.0.0.1:3001/episode/materialized/4a1937ae-761d-464b-ad22-e05cc9f12881

Web smoke passed for the primary: opening play, pause/resume, next-chapter
progression, current-item/timeline synchronization, and continuous
MUSIC/NARRATION playback assets. GPT's final artifact review marked
PHASE_5_3_DEMO_READY: YES and KEEP_BOTH, with the new episode as primary
and the previous episode as fallback.

Known non-blocking editorial debt: when the final artist is not the opening
anchor artist, the Outro should eventually return explicitly to the opening
Fang Datong anchor and explain why the route can reach the explored lineage.
Do not reopen Phase 5.3 solely for this issue. Human listening is still
required for English artist/genre pronunciation, Chinese-English transitions,
TTS pacing, and subjective program quality. No raw prompt, provider response,
hidden reasoning, credential, or signed URL is retained in this state record.

## Completed implementation

- **Phases 0–1:** typed episode/segment contracts, deterministic mock providers,
  progressive frontier runtime, browser playback, seek/skip, leave/resume, and
  full-materialization semantics.
- **Phase 1.5:** Postgres episode persistence, listener-scoped resume,
  repository abstraction, versioned SSE updates, and restart-safe runtime state.
- **Phase 2:** DeepSeek, Exa, Tavily, MiniMax, and music-provider seams with
  normalized usage/error accounting; mock mode remains credential-free.
- **Phase 3 / 3.5:** two-speed progressive intelligence, TTFS tracing, bounded
  search, structured FastStart/Curator/Writer roles, and human-reviewed guided
  discovery evaluation.
- **Phase 4.1–4.4:** browser-owned HTML5 audio runtime, provider-neutral audio
  assets, deterministic radio composition, retrieval ensemble, and MiniMax
  narration materialization with local object storage.
- **Phase 4.5:** bounded live episode assembly through catalog resolution,
  radio-script composition, music assets, and narration materialization.
- **Phase 4.6:** adaptive `ResearchPlan` preserved through the progressive
  pipeline, with deterministic execution limits.
- **Phase 4.7:** narrative-first chapters, unresolved music proposals retained
  for editorial context but excluded from playback, narration budgeting,
  explicit language selection, and visible-text/TTS-text separation.
- **Phase 4.7.1:** Writer synthesis policy hardened for structured DeepSeek
  Responses output, with reasoning disabled on the hot Writer path.
- **Phase 4.7.2:** live-probe music preflight. The local music chain now has a
  distinct readiness check, and probes resolve required anchors before any
  Exa, Tavily, DeepSeek, or MiniMax work is constructed.
- **Phase 4.8.1 (complete):** Writer receives typed, final-playback
  `NarrationSlotContext` values per narration slot (including distinct
  before-track and after-track contexts); application code owns numeric
  playback placement, normalizes chapter identity, fails explicitly on
  impossible narration placement, preserves multiple ordered blocks in a gap,
  and reports parsed/normalized Writer blocks safely.
- **Phase 4.8.2 (complete, merged in PR #24):** background research can regenerate one
  bounded typed `ResearchPlan` after a FastStart fallback, while retaining the
  deterministic one-Exa/two-Tavily execution cap. URLs are canonicalized before
  evidence deduplication and IDs; Evidence carries conservative provenance
  category/domain/preference metadata. Curator and Writer outputs can attach
  typed fact/correlation/causal/editorial-interpretation/uncertainty support
  records scoped to evidence IDs. Successful probe diagnostics expose the
  actual plan, provenance summaries, skeleton metadata, stage usage, and safe
  provider events. No raw prompts, responses, reasoning, credentials, or signed
  URLs are emitted.
- **Phase 4.8.3.1 (complete, merged in PR #25):** deterministic program timing plans
  use resolved music durations, weighted narration budgets, explicit infeasibility
  diagnostics, and planned-versus-actual timing summaries without paid providers.
- **Phase 4.8.3.2 (complete, merged in PR #26):** buffer-aware generation uses
  the derived `buffer_ahead_seconds` metric and materializes complete future
  chapters until either the chapter or seconds target is met. Current and
  future partial chapters are completed atomically before either stop bound;
  no server playback clock is added. The exact-head review and backend/web CI
  both passed, with no live/paid provider used.
- **Phase 4.8.2.1 (merged in PR #20):** Curator provider-schema failures
  are separated from application contract failures with stable reason codes.
  Unknown Curator evidence references are deterministically dropped before
  strict scope checks; empty evidence scopes remain valid but constrain Writer
  to transitions, adjacency, editorial framing, or explicit uncertainty.
  Failed assembly keeps a sanitized pre-Curator research snapshot and usage
  ledger for diagnosis.
- **Phase 4.8.2 implementation complete (PR #24):** the single authorized
  low-reasoning Fujii Kaze probe passed readiness, bounded research, Curator
  policy, 4/6 chapter-track bounds, 3 resolved tracks, and zero unresolved
  tracks. Historical follow-up probe failures below describe benchmark/content
  quality outcomes and do not roll back the implementation-complete status.
- Safe metrics: Curator 35.713s with 11,553 input / 8,180 output /
  4,807 reasoning tokens; output cap was not touched; Writer was 8/8/8
  parsed/normalized/final blocks and all 11 timeline segments were AUDIO_READY.


## Invariants to preserve

- `EpisodeOrchestrator` and lifecycle transitions stay deterministic; bounded AI
  roles do not decide lifecycle, spending, cancellation, or commitment.
- `TrackProposal -> MusicProvider catalog resolution -> ResolvedTrack` is the
  playback trust boundary. Unresolved proposals may remain in editorial output
  but are never playable or committable into the audio timeline.
- The committed/played prefix is immutable. Only speculative future chapters
  may be replanned or replaced.
- The browser owns playback time. Server state persists lifecycle, version,
  segment, and checkpoint data; it must not become a 1 Hz playback clock.
- Progressive generation stays roughly one to two chapters ahead and stops
  when its target buffer is satisfied or the listener becomes inactive.
- Search normalization produces Evidence. Candidate inference belongs to
  FastStart/Curator, and catalog identity is supplied only by resolution.
- Narration placement is derived after resolution from actual playable
  adjacency; each Writer block must match a typed slot allowlist, and
  Curator/Writer chapter numbers are never playback anchors. `parsed_blocks`
  diagnostics are normalized application models, not raw provider payloads.
- Mock mode is the default. Paid/network probes are explicit, bounded, and
  never part of ordinary tests or CI.

## Provider status

- **Default/local:** deterministic fake LLM/search/music/TTS/audio providers;
  zero credentials are required for development and CI.
- **Available live seams:** DeepSeek, Exa, Tavily, MiniMax, Audius, NetEase
  sidecar, and QQ-compatible music adapters. Audius playback credentials stay
  server-side behind the WaveCast proxy. NetEase readiness is checked through
  the local sidecar before live probes.
- **Operational boundary:** live mode requires explicit local configuration in
  the gitignored `.env`; missing live configuration surfaces an error rather
  than silently selecting a mock provider.
- **Not yet productized:** official TME/QQ integration, production queueing,
  social/publishing features, and broader provider/catalog coverage.

## Latest Fujii Kaze benchmark (sanitized)

The accepted Phase 4.8.1 biography benchmark ran once after local music
readiness passed. It was recorded against commit
`650537b4cd4637c212244255c79d2b53750a1e23`. No raw provider payloads,
credentials, hidden reasoning, or signed URLs are kept in the repository.

- FastStart fallback was **true**; `first_script_ready` / TTFS was **15,006
  ms**.
- The assembled program had **4 resolved tracks** across **6 Writer chapters**.
  Parsed, normalized, and final narration counts were each **10**, so no
  silent Writer block loss was observed.
- Music duration was **1,046 seconds**, planned narration was **152 seconds**,
  actual narration was **202 seconds**, and total program duration was
  **1,248 seconds** (a **16.19%** narration ratio).
- Timings were: background **8,012 ms**, Curator **42,659 ms**, Writer
  **10,906 ms**, and total assembly **97,923 ms**.
- Runtime/editorial checks: previous/next playback adjacency **passed**;
  silent Writer block loss **not observed (10 == 10 == 10)**;
  narrative-only placement **passed**; final narration placement **passed**.
- This validates editorial placement and timing instrumentation for the
  benchmark. It does **not** validate cross-artist discovery quality; that
  remains a human-review item.

## Phase 4.8 plan

1. **4.8.1 — Editorial correctness (complete):** preserve playback order and
   chapter semantics, align transition/intro/outro references with actual track
   indices, keep narration-only beats in place, and flag unsupported claims for
   review.
2. **4.8.2 - Research quality (complete):** evidence quality, provenance, bounded planning,
   query/facet usefulness, candidate grounding, and uncertainty reporting without
   expanding search budgets.
3. **4.8.3 - Program timing (complete):** improve target-duration adherence,
   narration pacing/ratio, actual-vs-planned segment durations, and buffer-aware
   timing without reintroducing a server playback clock.

## Phase 5.1 initial scope

The fixed benchmark set is: B1 Fang Da Tong biography, B2 Fang Da Tong to
Musiq Soulchild and broader Soul/Neo-Soul/R&B discovery, B3 UK Garage
genre/scene, and B4 Chinese rock across eras. The first stage evaluates
editorial thesis, discovery value, route coherence, musical insight, research
grounding, narrative/pacing, and after-listening effect. Spoken writing and
TTS delivery are evaluation dimensions, but prompt and voice tuning are
deferred polish work rather than Phase 5.1A objectives.

The immediate action is a read-only audit of Research, candidate generation,
Curator, catalog resolution, Writer, and TTS/composition to identify the actual
source of artist-local or obvious-track bias and propose the smallest
provider-neutral implementation plan. LIVE_ALLOWED: NO.

## First Phase 4.8.2 live result (sanitized)

The first bounded Fujii Kaze Phase 4.8.2 run was executed once against commit
`c1f3b7d4eb57f2f9add231bd6c4420f6c83c84dd`. Music readiness, FastStart, and the
bounded search budget passed, but assembly failed at the Curator boundary. The
outer failure was `EpisodeAssemblyError` with an underlying
`ProviderInvalidResponseError`; the then-current diagnostics could not
distinguish a structured-schema rejection from an application-level Curator
contract rejection. The exact Curator rule is not known from the retained safe
report. This historical run did not establish content-quality benchmark
acceptance;
4.8.2.1 then added the required distinction and preserved safe pre-Curator
evidence and usage for future review.

## Post-PR #20 Fujii Kaze regression (sanitized)

A single authorized post-merge regression ran against
`fdeace50d0047f7dede1b59d52bd15bc56d6f038` after music readiness and both
anchor preflights passed. Assembly failed at the Curator boundary with
`ProviderOutputLimitError`, mapped to `provider_output_limit`. No automatic
retry was performed, and no raw prompt, provider response, hidden reasoning,
credential, or signed URL was retained. This confirms the PR #20 failure
classification path but does not complete Phase 4.8.2 content-quality
acceptance.

## Post-PR #21 Fujii Kaze regression (sanitized)

A single authorized post-merge regression ran against
`12fa1a7126e6612917747ab30b87e9fb864e73fb` after local music readiness and
both anchor preflights passed. The bounded search stages completed, but
assembly timed out at the Curator boundary with `ProviderTimeoutError`,
mapped to `provider_timeout`. No automatic retry was performed, and no raw
prompt, provider response, hidden reasoning, credential, or signed URL was
retained. The historical benchmark acceptance remained incomplete; this does not
roll back the implementation-complete status recorded above.

## Phase 4.8.2 deadline repair (merged in PR #22)

PR #22 separates the background search deadline from the independent planner
deadline, raises the bounded deep-provider default timeout from 45 to 60
seconds, and preserves only the fallback `reason` alongside its safe
plan-source trace metadata. Its exact-head review and CI passed, and it was
merged as `410023cc03f2734d5a9966cacf5a25d094f8d4cc`.

## Post-PR #22 Fujii Kaze regression (sanitized)

The single authorized post-merge probe ran against
`410023cc03f2734d5a9966cacf5a25d094f8d4cc`. Music readiness and both
anchors passed. The adaptive planner ran successfully
(`research_plan_source=background_planner`) and bounded search remained
within budget, confirming the deadline repair. Curator then reached the
configured `12288` output cap and failed with
`ProviderOutputLimitError` / `provider_output_limit`.

The live probe did not expose its existing `max_chapters` request bound,
so this benchmark used the application default of 16 chapters instead of the
intended 6-chapter biography benchmark bound. No retry was performed; no raw
prompt, provider response, hidden reasoning, credential, signed URL, or full
research content was retained. The historical benchmark acceptance remained incomplete; this does not
roll back the implementation-complete status recorded above.

## Phase 4.8.2 benchmark-bound repair (historical, sanitized)

The repair added `--max-chapters` to the live probe, forwarded it
to `LiveEpisodeAssemblyRequest`, keeps its default at the application
default of 16, and fixes this benchmark at `max_tracks=4` /
`max_chapters=6`. It does not change the production default, token cap,
reasoning policy, retry policy, search budget, Writer, or frontend. No live run
is part of this repair.

## Post-PR #23 Fujii Kaze regression (sanitized)

The single authorized 4/6-bound probe ran against
`87bf89e86e55682c879b9a6c3c11140fa14f75cb` with effective deep timeout
60 seconds, `max_tracks=4`, and `max_chapters=6`. Music readiness
and both anchors passed; bounded background research completed. Curator still
reached the configured output boundary with `ProviderOutputLimitError`
and `provider_output_limit` (safe output usage was 12,285 of 12,288).
No retry was performed, and no raw prompt, provider response, hidden reasoning,
credential, signed URL, or full research content was retained. The historical benchmark acceptance remained incomplete; this does not
roll back the implementation-complete status recorded above.

## Phase 4.8.2 Curator policy repair (historical, sanitized)

The repair introduced `InferenceProfile.CURATOR`, preserving
the deep timeout, 12,288-token cap, transport, and bounded attempts while using
low reasoning effort. Only Curator switches to this profile; general
`InferenceProfile.DEEP`, FastStart, ResearchPlanner, Writer, grounding
contracts, schemas, search budgets, and retry behavior remain unchanged. No
live/paid provider call is part of this repair.

## Known deferred work

Production queue/worker infrastructure, official TME/QQ playback, richer music
catalog coverage, account/auth systems, recommendation training, persistent
cross-episode taste memory, social/publish/fork features, native apps, Ocean
Listen enrichment, and a broad UI redesign remain later work. Real provider
calls remain opt-in and must not leak raw prompts, responses, reasoning,
credentials, or signed playback URLs.

## Pointers and validation

- Long-lived product/architecture contract: [`CODEX_HANDOFF.md`](CODEX_HANDOFF.md)
- Architecture decisions: [`docs/adr/`](adr/), especially
  [ADR 0009](adr/0009-adaptive-research-planning.md) for adaptive research and
  [ADR 0011](adr/0011-deterministic-narration-slot-context.md) for the prior
  editorial-slot phase
- Recent milestones: [PR #20](https://github.com/ZakuZakuu/wavecast/pull/20),
  [PR #21](https://github.com/ZakuZakuu/wavecast/pull/21),
  [PR #22](https://github.com/ZakuZakuu/wavecast/pull/22),
  [PR #23](https://github.com/ZakuZakuu/wavecast/pull/23),
  [PR #24](https://github.com/ZakuZakuu/wavecast/pull/24),
  [PR #25](https://github.com/ZakuZakuu/wavecast/pull/25),
  [PR #26](https://github.com/ZakuZakuu/wavecast/pull/26),
  [PR #27](https://github.com/ZakuZakuu/wavecast/pull/27),
  [PR #29](https://github.com/ZakuZakuu/wavecast/pull/29),
  [PR #30](https://github.com/ZakuZakuu/wavecast/pull/30),
  [PR #31](https://github.com/ZakuZakuu/wavecast/pull/31),
  [PR #32](https://github.com/ZakuZakuu/wavecast/pull/32),
  [PR #33](https://github.com/ZakuZakuu/wavecast/pull/33),
  [PR #34](https://github.com/ZakuZakuu/wavecast/pull/34),
  [PR #35](https://github.com/ZakuZakuu/wavecast/pull/35). Earlier milestones
  remain available in Git history and the preceding project-state entries.
- Timing decision: [ADR 0012](adr/0012-deterministic-program-timing.md).

## Session handoff and recovery

This file is the current execution snapshot; `CODEX_HANDOFF.md` is the
long-lived product and architecture contract. A new Codex session should read
`AGENTS.md`, this file, `CODEX_HANDOFF.md`, and the relevant ADRs before acting.

The PR Loop state under the user-level `~/.codex/pr-loop/wavecast/` directory
contains PR metadata, exact HEADs, tests, CI, review SHAs, and merge state. It
is not the ChatGPT conversation state. If a long ChatGPT conversation must be
replaced, use the original `codex-with-chatgpt` HANDOFF flow and re-confirm the
current PR HEAD; never treat an old review as valid for a changed SHA. Do not
reset, stash, or overwrite a dirty checkout merely to synchronize it. Create a
clean worktree from canonical `origin/main` instead.

Credential-free validation:

```bash
uv run ruff check .
uv run mypy
uv run pytest
pnpm lint
pnpm typecheck
pnpm test:web
pnpm build
```

Opt-in live episode validation, only after local credentials and music
readiness are available:

```bash
curl -fsS http://127.0.0.1:3101/health
curl -fsS http://127.0.0.1:3101/ready
uv run python scripts/live_episode_probe.py --run-live \
  --topic "..." --anchor "Artist — Track" --anchor "Artist — Track" \
  --json-output /tmp/wavecast-live-episode.json
```

The live command is bounded and explicitly opt-in; never run it from CI or an
ordinary credential-free test run.

Operational rule for future live runs: when a live probe is requested, first
start the configured local music chain (NetEase-compatible upstream on port
3000, then `wavecast-music-dev` on port 3101) and verify both `/health` and
`/ready`. Do not report the probe as blocked merely because those local
processes are not already running. Stop only when the configured source/API
has changed, startup genuinely fails, or the required credentials/network are
actually unavailable.

Failed live probes must leave a sanitized structured diagnostic with stage,
mapped cause/reason, usage totals, and safe provider-event summaries. Routine,
reversible operational faults (for example, a stopped local service) should be
fixed autonomously. Block only for missing authority or credentials,
destructive actions, external provider/API changes, or a genuine
product/architecture decision.

## Phase 6C adaptive TTS director

Phase 6C adds a provider-neutral NarrationRole to composed narration
segments and a pure, bounded SpeechDirector that selects a SpeechProfile
from role plus a mixed CJK/Latin signal. The first profile is deliberately
small: role-specific speed values remain between 0.85 and 0.96, mixed-script
text is slowed by a fixed bounded delta, and no provider, search, LLM,
randomness, or episode mutation is involved.

Narration materialization selects the profile before cache lookup and passes
it to TTSProvider. Mock and MiniMax adapters include selected speed and
language fallback/override in cache identity; MiniMax maps only the documented
speed and language fields while retaining existing voice, volume, pitch, and
audio settings. Safe metadata records profile id/version, speed,
language_boost, narration role, and cache hit without storing text or provider
responses. Targeted regression coverage verifies role mapping, deterministic
bounded profiles, cache sensitivity, materializer propagation, and MiniMax
payload mapping. Actual pacing and pronunciation still require a later
bounded human listening pass.


## Phase 6D.1 role-aware deterministic arrangement

Phase 6D.1 keeps MixPlan schema version 1 and makes the deterministic
arrangement planner use the existing typed NarrationRole for physical
narration/music timing. Writer owns narration semantics and text; the planner
owns only bounded timeline placement and gain automation; Web mix playback and
the ffmpeg renderer remain execution consumers of the canonical plan.

The provisional policy is intentionally small:

- TRACK_INTRO anchors incoming music at the narration start, so a generic
  preceding crossfade cannot start the track too early.
- TRANSITION and INTRO keep the outgoing music overlap and admit incoming
  music one bounded second into the narration (or half the narration when
  shorter).
- OUTRO has no synthetic incoming music and remains over the final music tail.
- GENERAL preserves the existing direct-crossfade compatibility baseline.
- Voice clips remain sequential; music ducking continues to use the existing
  bounded gain automation primitives.
- Planning is pure and ready-prefix based: adding future ready segments may add
  future placements but cannot move existing segment starts.

This slice changes no Writer, TTS, MixPlan schema, Web mix engine, ffmpeg,
provider, or live behavior. Validation uses deterministic fixtures for role
semantics, prefix stability, voice ordering, gain bounds, and direct
music/music crossfade.
