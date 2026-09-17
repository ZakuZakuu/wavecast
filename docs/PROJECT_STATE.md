# WaveCast Project State

**Last updated:** 2026-09-17

## Product reminder

WaveCast is an AI-native guided-listening radio product: a listener starts a
program immediately, while bounded research, curation, writing, and narration
materialize a coherent episode just ahead of playback. It is a deterministic
streaming runtime with bounded intelligence, not a chatbot or a static playlist.

## Current milestone and main state

- **Current milestone:** Phase 4.8.1 — Editorial correctness / narration-slot
  integrity is in progress; the next planned milestones remain 4.8.2 Research
  quality and 4.8.3 Program timing.
- **Main:** `c289d0a1b54ef3c53de0cecad431d9615fbd392d` (merge of documentation hygiene PR #16, with live-music
  preflight work from PR #15). The working tree on main was clean when this state
  was recorded.
- **Immediate work:** keep deterministic script/track placement aligned with
  resolved playback adjacency, prevent narration loss, and expose sanitized
  Writer-to-timeline diagnostics. Research source quality belongs to Phase
  4.8.2; timing/budget redesign belongs to Phase 4.8.3.

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
- **Phase 4.8.1 (in progress):** Writer receives typed, final-playback
  `NarrationSlotContext` values per narration slot (including distinct
  before-track and after-track contexts); application code owns numeric
  playback placement, normalizes chapter identity, fails explicitly on
  impossible narration placement, preserves multiple ordered blocks in a gap,
  and reports parsed/normalized Writer blocks safely.

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

The final Phase 4.7.2 biography benchmark ran once after local music readiness
passed for both explicit anchors. No raw provider payloads or credentials are
kept in the repository.

- FAST used deterministic fallback; `first_script_ready` / TTFS was **15,002
  ms**.
- Curator took **40,920 ms**, Writer **10,566 ms**, and total assembly took
  **83,738 ms**.
- The skeleton contained five chapters: three playable Fujii Kaze tracks, one
  unresolved early piano-cover proposal, and one narration-only resolution
  beat. The unresolved proposal remained out of the timeline.
- The timeline contained five narration segments (61 actual seconds) and 828
  music seconds, for 889 seconds total and a 6.86% narration ratio. Narration
  was Chinese and the final outro followed the last playable track.
- Writer usage was 18,360 input / 1,530 output / **0 reasoning** tokens across
  five completed calls; no Writer response approached the 4,096-token limit.
  Curator used 5,932 reasoning tokens as expected for background DEEP work.
- Search usage was two Exa queries at `$0.014` actual cost and two Tavily
  queries consuming two credits. MiniMax made five calls for 563 usage
  characters.
- Editorial result: the YouTube/coffee-shop piano-cover origin survived as a
  narrative thread, and the international-breakout role of `死ぬのがいいわ`
  was clear. The result still felt closer to a playlist with short host links
  than a fully shaped radio episode. One transition's “next song” reference
  does not align cleanly with the actual next track, and promotional claims
  such as view counts need human source review. No unsupported gendered
  pronoun was observed. Cross-artist discovery quality was not validated; the
  playable set remained single-artist.

## Phase 4.8 plan

1. **4.8.1 — Editorial correctness (next):** preserve playback order and
   chapter semantics, align transition/intro/outro references with actual track
   indices, keep narration-only beats in place, and flag unsupported claims for
   review.
2. **4.8.2 — Research quality:** improve evidence source quality and provenance,
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
  [ADR 0011](adr/0011-deterministic-narration-slot-context.md) for this phase
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
