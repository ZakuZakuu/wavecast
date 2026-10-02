# ADR 0020: Buffered Streaming Runtime v2

## Status

Accepted for implementation.

This ADR supersedes the Phase 7A implementation assumption that the browser should
periodically request inline chapter generation through `ensure-buffer`, and the
production behavior that treated an unknown music duration as a fixed 30-second
playback boundary.

It does **not** supersede the durable Episode lifecycle, provider trust
boundaries, committed-prefix invariants, ProgressiveAssemblySession, browser-owned
playback clock, or canonical MixPlan direction established by earlier ADRs.

## Context

WaveCast's product thesis has always been experience-first:

- tapping a program should start relevant music immediately;
- expensive research, curation, writing, TTS, and music preparation should happen
  behind the music;
- a live Episode should grow ahead of playback and may later become a fully
  materialized, fixed, replayable, saveable, and shareable program;
- the user should be able to put the phone down and keep listening without
  babysitting generation.

The first implementation validated many important contracts using deterministic
or pre-materialized episodes. That path hid several runtime problems which became
obvious only after real providers were enabled:

1. the production opening track inherited a 30-second default duration from the
   mock audio provider when real provider metadata did not carry duration;
2. the browser called `ensure-buffer` periodically, and one request could keep an
   API process busy for tens of seconds while research, curation, resolution,
   writing, music preparation, and TTS ran serially;
3. a chapter was appended only after the entire narration + music unit became
   AUDIO_READY, so a slow or failed narration path could block otherwise playable
   music;
4. catalog resolution failures could make the whole progressive extension fail
   even when enough music remained to keep the listener moving;
5. generation failure was visible to the listener as a playback boundary or dead
   air instead of being absorbed by a recovery policy;
6. the legacy MixEngine attempted to maintain its own synthetic playback clock,
   which caused stutter, pause/resume problems, and seek instability. The browser
   audio element has since been restored as the authoritative playback clock.

These failures are symptoms of one architectural mismatch: generation and
playback were coupled too tightly.

The runtime must instead treat music playback as a latency budget. A normal
three-to-four-minute opening track should give the backend enough time to prepare
future content without imposing a fixed playback deadline.

## Decision

Introduce **Buffered Streaming Runtime v2**.

The runtime is organized around four independently owned responsibilities:

```text
                          Episode
                            │
                ┌───────────┴───────────┐
                │                       │
                ▼                       ▼
      Generation Coordinator      Playback Runtime
                │                       │
                ▼                       ▼
        Future Content State      browser <audio>
                │                       │
                ▼                       │
          Ready Queue ──────────────────┘
                │
                ▼
       Arrangement / DJ Plan
```

The core ownership rules are:

- **Browser owns playback time.**
- **Backend owns generation, recovery, and arrangement.**
- **Postgres owns durable Episode state and job state.**
- **The committed/played prefix is immutable.**
- **Speculative future may be replaced or replanned.**
- **A MATERIALIZED Episode is frozen.**
- **Generation failure must not stop music when a safe playable fallback exists.**

### 1. Remove fixed opening-duration semantics

There is no product-level 30-second opening boundary.

A music source has at least two different timing concepts:

```text
source_duration_seconds
playback_window
```

`source_duration_seconds` is factual provider/catalog metadata when known.

`playback_window` is an arrangement decision: full track, selected excerpt, or
a future dynamically chosen transition window.

A missing provider duration must remain unknown or be filled by a metadata probe.
It must never silently become a production playback boundary because a mock
provider used a default value.

The initial v2 baseline should prefer **full-track playback** when no explicit
arrangement window exists. This maximizes continuity and gives generation the
largest useful latency budget.

### 2. Generation begins automatically after Episode creation

Creating or resuming an active progressive Episode schedules generation work on
the backend.

The browser no longer owns generation cadence and must not be responsible for
repeatedly calling a command equivalent to `ensure-buffer`.

The frontend may still send:

- listener liveness / leave signals;
- playback checkpoints;
- explicit skip / preference actions;
- explicit "prepare full episode" requests.

Those signals may change generation priority or policy, but they do not execute
provider work directly.

### 3. Use a durable background Generation Coordinator

The first implementation should use a lightweight Postgres-backed job model
rather than an HTTP request or process-local background task as the authoritative
owner of expensive work.

A separate worker process/service may claim jobs using a lease or
`FOR UPDATE SKIP LOCKED` pattern.

The required properties are:

- restart-safe;
- one active generation owner per Episode;
- resumable from persisted `ProgressiveAssemblySession`;
- bounded retries by failure class;
- listener-aware cancellation / deprioritization;
- observable progress;
- no provider clients or cursors stored as process-local authoritative state.

Redis, Celery, Kafka, or Temporal are not required for the first v2 slice. They
may replace the job transport later without changing Episode semantics.

### 4. Replace request-driven chapter generation with a Ready Queue

Playback consumes only **playable ready units**.

The backend continuously tries to keep enough playable content ahead of the
listener.

The buffer target is defined by readiness, not by a fixed opening cutoff.

Initial policy:

```text
healthy if:
  at least one complete transition unit ahead
  AND approximately 90-180 seconds of playable audio ahead
```

The exact thresholds are configuration and telemetry driven.

A future policy may use:

- current source remaining duration;
- measured Research/Writer/TTS latency;
- catalog-resolution confidence;
- network state;
- requested narration density;
- whether the Episode is progressive or full-generation.

The important invariant is that playback is not forced to stop merely because a
heuristic frontier was reached.

### 5. Split Chapter identity from resource readiness

A Chapter remains the editorial/narrative unit, but its resources progress
independently.

Conceptually:

```text
ChapterPlan
  ├── MusicIntent
  │     ├── CANDIDATES
  │     ├── RESOLVED
  │     └── PLAYBACK_READY
  │
  ├── Narration
  │     ├── PLANNED
  │     ├── SCRIPT_READY
  │     ├── AUDIO_GENERATING
  │     └── AUDIO_READY
  │
  └── Arrangement
        ├── WAITING_FOR_INPUTS
        └── READY
```

The public Segment model may remain simpler, but internal generation must not
require every resource in a chapter to become ready atomically.

Examples:

- music ready, narration TTS late -> music may still play;
- narration ready, preferred music unresolved -> use an alternate playable track;
- narration generation fails -> skip narration or use a deterministic minimal
  transition if policy allows;
- one speculative chapter fails -> skip or replace that chapter without
  invalidating the committed prefix.

### 6. Define explicit graceful-degradation policy

Only failures that make safe playback impossible are fatal to listening.

Initial policy:

| Failure | Runtime behavior |
| --- | --- |
| opening track not playable | fail Episode start or choose a verified opening alternate |
| Research timeout/failure | continue with FastStart / existing evidence / simpler route |
| Curator recoverable contract error | normalize safe editorial metadata |
| Curator unavailable | use persisted route or bounded fallback route |
| primary track resolve failure | try equivalent provider source, then ranked slot alternates |
| all alternates for one slot fail | skip/replace that speculative slot |
| Writer failure | continue without narration or use deterministic minimal narration |
| TTS failure | skip narration audio; continue music |
| next content not yet ready | continue current music when safe |
| worker/process restart | resume generation from durable session/job state |
| listener leaves | stop or deprioritize speculative work after bounded cleanup |

The runtime must surface diagnostic state for observability, but a recoverable
provider failure should not become a visible `Request failed` playback error.

### 7. Make music selection catalog-aware without weakening identity safety

The existing playback trust boundary remains:

```text
TrackProposal
  -> MusicProvider catalog resolution
  -> ResolvedTrack
  -> playable audio
```

An unresolved LLM proposal is never playable.

However, a chapter should no longer depend on exactly one artist/title pair.

Introduce a slot-oriented resolution model:

```text
MusicSlotIntent
  editorial role
  musical constraints
  ranked candidates[]
  resolved alternatives[]
```

Resolution order:

1. preferred candidate;
2. equivalent recording/source from another provider;
3. ranked alternate candidate for the same editorial slot;
4. replacement candidate from catalog-aware retrieval;
5. skip the speculative slot if no safe candidate is playable.

Longer term, Curator should increasingly choose from **real catalog candidates**
instead of inventing an exact track first and verifying it afterward.

This ADR does not relax canonical artist/title matching for an individual
candidate.

### 8. Progressive and full generation are policies of the same Episode

Do not maintain separate Episode identities or separate intelligence pipelines.

`generation_mode=PROGRESSIVE`:

- start playback immediately;
- generate modestly ahead;
- stop/deprioritize speculative work when listener becomes inactive;
- allow bounded replanning of uncommitted future.

`generation_mode=FULL`:

- keep the same Episode id and durable session;
- continue from already committed/generated work;
- drain the intended future until the program is complete;
- snapshot required music assets and narration assets;
- freeze the final arrangement.

A listener may switch an in-progress Episode from PROGRESSIVE to FULL.

The system must not regenerate a new "similar" program when doing so.

### 9. Episode identity and immutability contract

Episode uniqueness is defined by persistent Episode identity, not by a prompt
being reproducible.

The lifecycle remains:

```text
EpisodeSeed
  -> LiveEpisode(PROGRESSIVE or FULL)
  -> MaterializedEpisode
  -> optional PublishedEpisode
```

Invariants:

- exposed/played committed segments never silently change;
- durable generated assets referenced by committed segments remain stable;
- speculative future may be replaced before commitment;
- materialization completes the same Episode;
- MATERIALIZED freezes the timeline, chosen track identities, narration assets,
  and canonical arrangement revision;
- save/share/export operates on a frozen revision;
- replay of a frozen Episode is deterministic except for unavoidable external
  source availability, which should be mitigated by owned snapshots where
  permitted.

### 10. Keep browser playback simple and authoritative

The v2 runtime preserves the post-refactor playback rule:

> the actual browser media element is the authoritative playback clock.

The backend persists lifecycle/checkpoint state but never attempts to drive a
1 Hz playback clock.

SSE may notify the browser that new ready content or a new arrangement revision
exists. It must not continuously push transport position or overwrite immediate
user pause/resume/seek intent.

The player should never seek an audio element merely to correct small drift
against a synthetic server or React clock.

### 11. Reintroduce DJ behavior as declarative arrangement, not transport

Preserve the canonical `MixPlan` idea, but treat it as a deterministic
**ArrangementPlan** consumed by the stable playback transport.

Curator decides:

- what to play;
- why it belongs;
- narrative role / adjacency.

Writer decides:

- what the host says.

Arrangement/DJ logic decides:

- source window;
- transition point;
- crossfade duration;
- music gain automation;
- narration ducking;
- fade-in/fade-out;
- optional overlap;
- eventually beat/section-aware transitions.

Example conceptual arrangement:

```text
Music A
  source 00:00 -> 02:14
  fade_out 1.2s

Narration
  enters at Music A 02:12
  music_gain_under_voice -12 dB
  voice_fade_in 0.3s

Music B
  source_start 00:07
  overlap 1.5s
```

The first v2 implementation may use conservative fixed transition templates.

The same deterministic arrangement representation should be usable by:

- realtime Web playback;
- later offline ffmpeg mixdown;
- frozen MaterializedEpisode export.

This prevents realtime playback and exported/shared playback from becoming two
different programs.

### 12. Loudness and narration/music balance belong to Arrangement

Volume balance is not an LLM decision.

The arrangement layer owns deterministic audio policy such as:

- narration target gain / loudness;
- music ducking level;
- attack/release/fade timing;
- transition overlap;
- optional track normalization.

Writer may emit provider-neutral style or pause cues, but not authoritative dB
or timestamp automation.

Future loudness analysis may refine these values without changing Writer or
Curator contracts.

### 13. Audio-analysis seam and Narration P0 timing policy

The provider-neutral timing/analysis seam is now partially active for Narration
P0. Timed lyrics are treated as a **timing signal**, not as LLM content.

The P0 contract is:

```text
TrackTimingProfile {
  source_duration_seconds
  sections? {
    kind
    start
    end
  }
  vocal_intervals? {
    start
    end
  }
  lyric_lines? {
    start
    end
  }
}
```

Provider adapters may use a platform lyric endpoint to obtain timestamps, but
raw lyric text is discarded at the provider boundary. WaveCast persists only
the timing intervals needed for deterministic arrangement. The Writer does not
receive the lyrics in this slice.

When timing is present, Arrangement may:

- wait until the final outgoing vocal has ended before entering narration;
- use a trailing instrumental outro for a longer, cleaner voice overlap;
- delay incoming music so its first lead vocal does not begin under narration;
- derive conservative intro, instrumental-gap, vocal, and outro sections.

When timing is absent or the provider call fails, playback remains valid and
Arrangement falls back to the existing fixed conservative geometry.

The P0 narration lookback is bounded to 12 seconds. This remains inside the
immutable programme feed's current 30-second render holdback, so a timing-aware
transition cannot require rewriting already-published chunks.

Still deferred:

- raw/full lyric text in WaveCast intelligence prompts;
- LLM lyric semantics or quotation/reasoning;
- beat grid/downbeat/energy analysis;
- advanced adaptive DJ transition selection.

This keeps timing deterministic and provider-neutral while leaving richer audio
analysis as a later extension.

### 14. Frontiers remain useful, but they change meaning

Keep conceptual frontiers:

```text
Playback Frontier
Committed Frontier
Playable/Ready Frontier
Planning Frontier
Research Frontier
```

But the Playable Frontier is not a hard wall that forces the current source to
stop.

It describes how much **future replacement/transition content is guaranteed
ready**.

The current source may continue safely while the Ready Queue recovers.

The UI may still visualize generated/ready content, but internal buffer policy
must not expose implementation deadlines as user-visible playback failures.

### 15. Events and observability

Retain SSE as the simple one-way episode update channel.

Prefer semantic events/state changes such as:

```text
generation_started
route_ready
music_slot_resolved
narration_script_ready
narration_audio_ready
arrangement_ready
ready_queue_changed
generation_degraded
generation_paused
materialization_complete
```

Do not expose worker internals to frontend components.

Required v2 metrics include:

- time_to_first_audio;
- time_to_first_ready_successor;
- ready_audio_seconds_ahead;
- generation_underrun_count;
- generation_stage_latency;
- resolution_primary_success_rate;
- resolution_alternate_success_rate;
- narration_skip_rate;
- TTS failure/degradation rate;
- time spent with only current music playable;
- provider error rate;
- materialization completion latency.

The most important product SLO is:

> Once first audio starts, recoverable generation failures should not create
> avoidable dead air.

## Migration plan

Implement v2 incrementally while keeping the current stable browser transport.

### Slice A — correct source timing and Episode playback semantics

- remove mock 30-second duration leakage from live music;
- represent unknown/real source duration correctly;
- default to full-track playback when no arrangement window is known;
- preserve current pause/resume/seek behavior.

### Slice B — durable generation jobs

- introduce Postgres-backed generation job/lease state;
- add a Railway worker service or equivalent worker process;
- trigger generation after Episode start/resume;
- stop using browser `ensure-buffer` as the generation owner;
- persist safe job progress/error state.

### Slice C — ready queue and independent resource readiness

- expose music and narration readiness separately;
- allow playable music to proceed without narration;
- introduce ready-ahead metrics and buffer policy;
- classify errors as fatal vs degradable.

### Slice D — resilient music-slot resolution

- add ranked alternatives;
- reuse cross-provider equivalents;
- add catalog-aware replacement;
- skip only the failed speculative slot when necessary.

### Slice E — progressive/full convergence

- make FULL drain the same durable Episode/session;
- ensure no committed content changes;
- freeze timeline/arrangement/assets on MATERIALIZED;
- preserve save/share/export identity.

### Slice F — deterministic Arrangement v2

- restore declarative MixPlan/ArrangementPlan on top of the stable browser clock;
- add preloading, crossfade, ducking, and volume policy conservatively;
- keep realtime playback and ffmpeg materialization based on the same plan.

### Deferred

- raw/full lyrics in intelligence prompts and LLM lyric semantics;
- beat/downbeat/energy analysis beyond the P0 timestamp-only timing seam;
- advanced adaptive DJ transition selection;
- native apps;
- generalized distributed workflow infrastructure.

## Rejected alternatives

### Keep the current 30-second frontier and make generation faster

Rejected. Real provider latency is variable and sometimes exceeds 30 seconds.
A fixed playback deadline couples product continuity to backend latency and
wastes the natural latency budget of full songs.

### Retry `ensure-buffer` more aggressively from the browser

Rejected. More retries make duplicate paid work and concurrency races more
likely while leaving generation ownership in the wrong layer.

### Pre-generate every Episode before playback

Rejected as the default. It increases time-to-first-audio and cost, and gives up
the adaptive progressive experience. Full materialization remains an explicit
policy for users who want it.

### Let unresolved music fall back to approximate title matches

Rejected. Playback identity must remain deterministic and trustworthy.
Recovery uses ranked alternates, equivalent providers, replacement candidates,
or slot skipping instead.

### Restore the old synthetic MixEngine clock

Rejected. Real production listening demonstrated stutter, pause/resume failure,
and seek instability. Arrangement must be layered over browser-owned transport.

### Put exact transition timestamps and gain values in LLM output

Rejected. Lifecycle, playback timing, and gain automation are deterministic
application responsibilities. AI may provide editorial intent, not authoritative
transport commands.

## Consequences

The runtime becomes more complex internally because generation, readiness,
playback, and arrangement are explicitly separated.

That complexity is intentional: these concerns already exist in the product and
coupling them produced user-visible failures.

The design preserves most existing investments:

- durable Postgres Episode snapshots;
- CAS persistence;
- SSE;
- ProgressiveAssemblySession;
- Research / Curator / Writer roles;
- MusicProvider catalog trust boundary;
- MiniMax narration assets;
- browser-owned playback clock;
- canonical MixPlan and ffmpeg mixdown direction.

The main implementation replaced by v2 is:

- browser-driven periodic `ensure-buffer`;
- inline request-owned expensive generation;
- atomic all-or-nothing chapter readiness;
- fixed mock-derived opening duration/frontier behavior.

Successful implementation should make WaveCast feel like a continuous radio
product first and an AI generation system second.

## Adaptive buffer implementation — September 27, 2026

Refill admission and generation stopping share a deterministic decision using
the browser checkpoint, playable seconds ahead (optional narration excluded as
a blocker), successor readiness, mode, and a bounded recent refill latency.
The latency estimate lives in the existing Episode snapshot, defaults to zero
for older records, rises immediately for slower successful refills, and decays
by 20% after faster ones. No schema migration is required.

The target is the configured baseline or 1.5 times latency plus 30 seconds,
whichever is larger; the adaptive contribution is capped at 600 seconds. The
one/two-chapter cap still bounds generation and prevents repeated healthy-queue
jobs. No successor always requires preparation. Less than 30 seconds remaining
without a successor is urgent; this is not a provider deadline or a new
cross-Episode queue priority system. FULL keeps its existing explicit drain path.

This deliberately uses per-Episode successful refill wall time rather than a
global provider percentile service. Failed/deferred refills are not observations.
Worker ownership/lease hardening and queue prioritization are separate concerns.
An already healthy queue skips expensive planning but still permits the existing
browser-ended recovery to start its ready successor. No transport, timeline
immutability, catalog identity, or seek-frontier contract changes.


## Immutable programme feed decision — September 28, 2026

Production listening on iOS exposed a boundary the realtime two-deck browser
renderer cannot make reliable enough: independent media elements may buffer,
seek, resume, and surface system-media state independently even when they share
one canonical MixPlan. Gain automation also belongs in the rendered audio, not
in best-effort per-element browser volume updates.

The primary listener transport therefore becomes one logical rendered programme
feed. MixPlan remains the canonical editorial/arrangement contract; ffmpeg (or a
future equivalent deterministic renderer) executes it before the bytes reach the
listener. The Web client consumes one media source and no longer owns mixing.

The programme feed has five invariants:

1. Rendered audio is immutable.
2. Generation may only append beyond the render frontier.
3. Play, pause, seek, replay, and device/system-media actions never mutate
   programme content or already-rendered bytes.
4. Live playback and the final cached/exported programme consume the same
   rendered timeline rather than independently re-rendering editorial history.
5. A transition is committed only after every input required for that transition
   is ready. Unfinished narration cannot be silently skipped by the immutable
   renderer and inserted later behind the frontier.

Publication is chunked. Each immutable transport chunk stores its absolute
programme interval, the fingerprint of the exact sliced MixPlan that produced
it, and a content hash. Before appending new chunks, the renderer recomputes the
fingerprint for every frozen interval against the newest MixPlan. Any difference
is an immutability violation rather than permission to rewrite history.

A render holdback keeps the unresolved tail speculative. The initial policy
holds back 30 seconds and publishes complete six-second chunks. This is longer
than the current deterministic crossfade/host transition lookback, so a later
successor can still change the outgoing song's tail without touching published
audio. When timing profiles introduce earlier lyric/section-aware transition
points, the commit-horizon policy must be extended explicitly rather than
silently shortening this guarantee.

The live transport is an HLS EVENT playlist over immutable AAC/MPEG-TS chunks.
The playlist itself is mutable and append-only; referenced chunks are immutable.
A MATERIALIZED/PUBLISHED Episode may close the feed with ENDLIST. Final M4A/MP3
export should be derived from the already-published programme timeline, ideally
by remuxing rather than regenerating arrangement decisions.

This supersedes the two-HTMLAudioElement realtime mixer as the target production
transport. The existing browser renderer remains a temporary compatibility
fallback while the single-source player is migrated. The investment being kept
is substantial: provider selection, progressive generation, narration assets,
Arrangement primitives, canonical MixPlan, gain envelopes, source snapshots,
and ffmpeg rendering all remain valid and move one layer earlier in the stack.
