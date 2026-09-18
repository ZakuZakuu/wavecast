# WaveCast Project State

**Last updated:** 2026-09-18

## Product reminder

WaveCast is an AI-native guided-listening radio product: a listener starts a
program immediately, while bounded research, curation, writing, and narration
materialize a coherent episode just ahead of playback. It is a deterministic
streaming runtime with bounded intelligence, not a chatbot or a static playlist.

## Current milestone and main state

- **Current milestone:** Phase 4.8.2 — Research quality (implementation in
  progress on a feature branch; no live providers are being run).
- **Main:** `650537b4cd4637c212244255c79d2b53750a1e23` (merged PR #18, safe
  live-failure diagnostics). Main is clean before the current Phase 4.8.2
  working changes.
- **Immediate work:** preserve the existing 4.8.1 playback-slot contract while
  making background research topic-adaptive, provenance-aware, and safely
  diagnosable. Timing/playback changes remain deferred to Phase 4.8.3.

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
- **Phase 4.8.2 (in progress):** background research can regenerate one
  bounded typed `ResearchPlan` after a FastStart fallback, while retaining the
  deterministic one-Exa/two-Tavily execution cap. URLs are canonicalized before
  evidence deduplication and IDs; Evidence carries conservative provenance
  category/domain/preference metadata. Curator and Writer outputs can attach
  typed fact/correlation/causal/editorial-interpretation/uncertainty support
  records scoped to evidence IDs. Successful probe diagnostics expose the
  actual plan, provenance summaries, skeleton metadata, stage usage, and safe
  provider events. No raw prompts, responses, reasoning, credentials, or signed
  URLs are emitted.

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
  benchmark. It does **not** validate cross-DJMAX discovery quality; that
  remains a human-review item.

## Phase 4.8 plan

1. **4.8.1 — Editorial correctness (complete):** preserve playback order and
   chapter semantics, align transition/intro/outro references with actual track
   indices, keep narration-only beats in place, and flag unsupported claims for
   review.
2. **4.8.2 — Research quality (current):** improve evidence source quality and provenance,
   query/facet usefulness, candidate grounding, and uncertainty reporting without
   expanding search budgets.
3. **4.8.3 — Program timing:** improve target-duration adherence, narration
   pacing/ratio, actual-vs-planned segment durations, and buffer-aware timing
   without reintroducing a server playback clock.

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
- Recent milestones: [PR #10](https://github.com/ZakuZakuu/wavecast/pull/10),
  [PR #11](https://github.com/ZakuZakuu/wavecast/pull/11),
  [PR #13](https://github.com/ZakuZakuu/wavecast/pull/13),
  [PR #14](https://github.com/ZakuZakuu/wavecast/pull/14),
  [PR #15](https://github.com/ZakuZakuu/wavecast/pull/15)

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
