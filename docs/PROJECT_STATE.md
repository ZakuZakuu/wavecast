# WaveCast Project State

**Last updated:** 2026-09-21

## Product reminder

WaveCast is an AI-native guided-listening radio product: a listener starts a
program immediately, while bounded research, curation, writing, and narration
materialize a coherent episode just ahead of playback. It is a deterministic
streaming runtime with bounded intelligence, not a chatbot or a static playlist.

## Current milestone and main state

- **Current milestone:** Phase 5.3 — Radio writing quality.
- **Current stage:** Phase 5.3A is implementing a language-scoped Chinese
  music-radio rubric, corpus notes, self-authored fixtures, and credential-free
  tests. Writer prompts and runtime contracts remain unchanged in this slice.
- **Canonical main:** 71bc98560a9c57c76eb8021791350f29b0c1a225 (origin/main; includes
  merged PR #39 and subsequent sanitized mainline updates); verify remote HEAD
  before acting.
- **Last completed code milestone:** PR #39 merged at
  70dc2f0f446e8e1ab7e28eb930a2fb8665416b24, closing Phase 5.2 narration/playback
  correctness and physical-gap cardinality.
- **Immediate work:** finish Phase 5.3A, run credential-free tests and static
  validation, then open the normal PR Loop review. Do not run live/paid
  providers; Phase 5.3B will decide whether a minimal zh-CN Writer prompt
  change is justified.

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
