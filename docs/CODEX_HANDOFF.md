# Codex Handoff — AI Music Radio / Guided Listening MVP

**Status:** Ready for implementation  
**Target:** Hackathon prototype with production-minded architecture  
**Primary objective:** Build the smallest end-to-end product that proves the listening experience, streaming generation model, and research/curation intelligence.

---

# 1. Product thesis

The product is an AI-native music radio / guided-listening application.

A user should be able to open the app, see interesting program ideas, tap one, and immediately hear relevant music. While the user is listening, the system researches the topic, curates the next tracks, writes natural host narration, generates speech, and continuously materializes the episode a little ahead of playback.

The product should feel like a music app or radio/podcast platform, not like a chatbot wrapped around a playlist.

The core product unit is not a playlist and not a static podcast file. It is an **Episode** that can begin as a live, progressively generated experience and later become a fully materialized, fixed, shareable program.

A useful conceptual contrast:

```text
Traditional playlist:
Song -> Song -> Song

Typical AI DJ:
Song -> short comment -> Song

This product:
Topic -> Story -> Song -> Explanation -> Song -> Discovery -> Interaction -> Branch
```

The core quality bar is simple:

> If a user starts a 30-minute session, puts the phone down, and does nothing else, would they willingly keep listening?

---

# 2. Product principles

## 2.1 Listening quality matters more than novelty

The existence of AI-generated radio is not enough. Existing products can already search related videos, generate generic script, and synthesize speech. Our differentiation should come from:

- strong research;
- tasteful music curation;
- well-paced narrative structure;
- natural TTS;
- correct timing of narration;
- smooth music/narration transitions;
- low interaction burden;
- adaptive future content.

The system should avoid "LLM writes a paragraph, TTS reads it, then another song plays" as its core behavior.

## 2.2 Feed first, prompt second

The homepage should look like a normal content product, not an empty AI prompt box.

Examples of program cards:

- 为什么 Persona 5 听起来这么“东京”？
- 从 Beatles 到 Oasis：英伦摇滚到底传承了什么？
- 你可能一直误解了 City Pop
- 游戏最终 Boss 为什么总爱用合唱？
- 从 Blinding Lights 出发，回到真正的 80s Synthpop

Program cards are cheap **proposals**, not fully generated episodes.

A separate "Create" flow may later provide structured choices such as:

- learn about an artist;
- understand a genre;
- game/film music;
- stories behind songs;
- explore outward from one song;
- casual companion listening;
- duration;
- narration density;
- tone/style.

Free text is optional, not the only entry point.

## 2.3 Start immediately, generate behind the music

When possible, the program card should already know an opening track. Clicking the card should start music immediately while the expensive AI pipeline runs in the background.

The system does **not** need to generate the episode instantly. It needs to **start the episode instantly**.

This creates a valuable latency budget: a three-to-four-minute song gives the backend ample time to research, plan, write, and synthesize the next narration.

## 2.4 Past is fixed; future can adapt

The system should treat an episode as a growing timeline:

- content already played/exposed is committed and stable;
- content already generated may be seekable;
- future content is speculative and may change based on user feedback.

This enables interactive adaptation without making the timeline incoherent.

---

# 3. MVP scope

The MVP must prove the core listening loop. Do not overbuild community, recommendation ML, account systems, or full production infrastructure before this loop works.

## MVP user flow

1. User opens Home.
2. Home shows 8–12 program cards generated from fixture/mock data initially.
3. Each card contains title, topic, estimated duration, procedural cover, and an opening track.
4. User taps a card.
5. Opening music starts immediately.
6. Backend creates a `LiveEpisode` and begins research/curation/planning.
7. Narration and future music chapters materialize incrementally.
8. Player transitions naturally among music and narration.
9. User can:
   - pause/resume;
   - seek backward within generated material;
   - not seek into ungenerated future;
   - skip/next;
   - optionally like/dislike or indicate "less talking" / "explain more" later;
   - leave and return;
   - request full generation/materialization.
10. Fully materialized episodes can be saved.
11. Publishing/share/Fork can remain a later milestone, but architecture must not block them.

## Explicit non-goals for first milestone

- full social network;
- real recommendation model training;
- complex authentication;
- perfect responsive mobile polish;
- generative image covers;
- full TME integration;
- deep audio analysis on every track;
- fully autonomous unbounded research;
- native iOS/Android apps.

---

# 4. Key lifecycle model

The central architecture is:

```text
EpisodeSeed
   ↓
LiveEpisode
   ↓ user listens while future materializes
MaterializedEpisode
   ↓ optional future milestone
PublishedEpisode
```

## 4.1 Episode Seed

Created cheaply for a homepage program proposal.

Minimum fields:

```text
id
title
topic / intent
short_description
estimated_duration
opening_track_ref
cover_params
generation_profile
created_at
```

No expensive full research, script, or TTS should be required to create a seed.

## 4.2 Live Episode

Created when the user starts listening.

A Live Episode has:

- a mutable speculative future;
- a persistent committed past;
- current playback location;
- generation frontiers;
- a Program Skeleton that may be patched;
- research/evidence bundles;
- materialized segments;
- current generation mode.

## 4.3 Materialized Episode

All intended chapters and narration are complete and fixed.

Properties:

- complete timeline;
- all narration audio cached;
- arbitrary seek;
- stable replay;
- ready for offline/save/share/comment features;
- no silent mutation of already published content.

---

# 5. Frontiers and streaming generation

Do not model generation as "one request returns one full episode".

Maintain at least these conceptual frontiers:

```text
Playback Frontier
    <
Committed / Seekable Frontier
    <=
Generated Audio Frontier
    <
Program Planning / Research Frontier
```

Interpretation:

- **Playback frontier:** where the user currently is.
- **Committed frontier:** content that must no longer change.
- **Generated audio frontier:** material already available for immediate playback.
- **Planning/research frontier:** future structure known cheaply, but not fully materialized.

Recommended operating target:

```text
User playback:             ~04:00
Audio ready through:       ~10:00
Program loosely planned:   ~20:00
Research coverage:         ~30:00
```

Exact timing is heuristic and may evolve.

## Buffer policy

Default progressive mode should attempt to maintain approximately:

- two chapters ahead, or
- five to eight minutes ahead,

whichever is more useful for the current program.

Do not keep generating indefinitely if the user leaves.

---

# 6. Chapters and segments

A program is made of chapters. A chapter may contain one or more timeline segments.

Example:

```text
Chapter 1
  MusicSegment(opening track)

Chapter 2
  NarrationSegment
  MusicSegment

Chapter 3
  NarrationSegment
  MusicSegment
```

A simpler serialized timeline may look like:

```text
S0 MUSIC
S1 NARRATION
S2 MUSIC
S3 NARRATION
S4 MUSIC
...
```

Suggested segment lifecycle:

```text
PLANNED
  ↓
SCRIPT_READY             # narration only / track chosen for music
  ↓
AUDIO_GENERATING         # narration TTS only
  ↓
AUDIO_READY
  ↓
COMMITTED
  ↓
PLAYED
```

Music and narration may require separate concrete sub-states internally, but keep a consistent public model.

---

# 7. User interaction semantics

## Seek

- User may seek backward within generated/committed content.
- User may seek anywhere inside a fully materialized episode.
- User may **not** seek into ungenerated future content.
- The UI should make the generated frontier understandable; a partially filled/bright timeline is acceptable.

## Next / skip

`Next` conceptually moves to the next chapter, even if the icon resembles a normal next-track control.

If narration for the next chapter is not ready but its track is known and playable, start the track rather than blocking.

Repeated skip behavior is a strong preference signal and may trigger replanning of future chapters.

## Previous

Return to prior committed/generated content without regenerating it.

## Leave/exit

When the listener leaves the episode:

- mark the session inactive;
- stop scheduling new speculative work;
- cancel pending work where cancellation is practical;
- do not corrupt already completed results;
- persist enough state to resume later.

Already-started tiny TTS/search calls do not need heroic cancellation if finishing them is cheaper/safer than interrupting.

## Return/resume

Restore timeline, playback position, generated frontiers, skeleton, and cached artifacts.

## Full generation

Expose an explicit action such as "Prepare full episode" / "Generate full episode".

This changes mode from progressive generation to full materialization.

Use cases:

- user plans to drive;
- offline preparation;
- user likes the topic and wants the whole program;
- saving/publishing/sharing.

---

# 8. Agent architecture

The AI layer should consist of multiple bounded roles managed by deterministic orchestration.

```text
                         EpisodeOrchestrator
                                  │
                ┌─────────────────┼─────────────────┐
                ▼                 ▼                 ▼
          ResearchAgent      CuratorAgent      WriterAgent
                │                 │                 │
         Search/metadata      Program plan       Script/TTS cues
                │                 │                 │
                └─────────────────┴─────────────────┘
                                  │
                                  ▼
                             Materializer
                                  │
                        ┌─────────┴─────────┐
                        ▼                   ▼
                  MusicProvider         TTSProvider
```

A small `Replanner` handles future-plan patches after user feedback.

## 8.1 Research Agent

Purpose: understand the musical/topic space and produce evidence-backed candidate material.

Inputs:

- user intent;
- anchor tracks/artists/topics;
- current program context;
- prior user signals if any;
- existing evidence cache.

Tools:

- Exa discovery;
- Tavily research;
- optional Serper exact fallback;
- MusicBrainz;
- Last.fm;
- possibly cached AudioAnalysis profiles.

Responsibilities:

- form taste hypotheses;
- decide what needs to be researched;
- generate bounded search queries;
- collect and normalize evidence;
- discover candidate tracks/artists/scenes;
- attach source/evidence references;
- report uncertainty.

It should **not** directly mutate episode lifecycle state.

Suggested budget controls:

```text
max_rounds: 2 initially
max_total_queries: ~10 initially
per-call timeout
soft cost budget
```

## 8.2 Curator Agent

Purpose: turn evidence/candidates into a coherent listening journey.

Inputs:

- ResearchBundle;
- user taste hypothesis;
- track availability;
- existing committed chapters;
- optional acoustic features.

Outputs a `ProgramSkeleton`.

Useful narrative-role taxonomy:

```text
anchor
validation
bridge
contrast
discovery
resolution
```

Curation should prefer an intentional exploration curve:

```text
very close to known taste
  -> close with one new element
  -> adjacent artist/scene
  -> surprising but explainable jump
  -> coherent resolution
```

Avoid simply returning nearest-neighbor tracks.

## 8.3 Writer / Showrunner Agent

Purpose: write narration that sounds natural when spoken and supports the listening experience.

Inputs:

- current chapter plan;
- relevant evidence only;
- previous committed transcript;
- next/previous track context;
- host style;
- target narration duration/density.

Outputs structured narration:

```text
text
TTS cues
intended duration
evidence ids
optional transition metadata
```

The Writer should not browse the web by default, should not swap tracks, and should not invent facts outside evidence.

Write for speech, not for essays. Favor natural spoken rhythm, short clauses, deliberate pauses, and restrained emotion.

## 8.4 Replanner

Inputs:

- current ProgramSkeleton;
- committed chapters;
- speculative chapters;
- user feedback/events.

Examples of feedback:

- skipped a track;
- liked a track;
- "less talking";
- "tell me more";
- repeated next/skip actions.

Output: a bounded patch affecting only uncommitted future content.

---

# 9. Search strategy

Search provider selection has already been tested using a difficult long-tail music example around 3rd Coast / DJMAX.

Current routing:

```text
DISCOVERY -> Exa Auto
RESEARCH  -> Tavily
EXACT     -> Serper fallback
```

## Why

### Exa Auto

Use for semantic discovery and expanding from known music into adjacent artists/scenes/eras.

### Tavily

Use for background research and content/evidence extraction from web pages, forums, YouTube descriptions/transcripts, music history material, etc.

### Serper

Use for exact entity/phrase lookup, ambiguity resolution, and fallback when search confidence is low.

Do **not** query all three providers for every question. Route by intent.

Normalize provider output into a common internal schema, for example:

```text
SearchResult {
  title
  url
  snippet
  content?
  score?
  published_at?
  provider
  query
}
```

---

# 10. Music metadata and recommendation evidence

Use structured sources to reduce hallucination and entity confusion.

## MusicBrainz

Useful for:

- artist identity;
- recordings;
- releases;
- works;
- ISRC;
- canonical relationships.

## Last.fm

Useful for:

- similar tracks/artists;
- tags;
- collaborative/community similarity signals.

Do not treat Last.fm similarity as final curation truth; it is evidence/candidate generation only.

---

# 11. Optional audio understanding: Ocean Listen

Repository: `ennisaaaaaaaa-stack/ocean-listen`

Treat as optional/offline enrichment, not a hard dependency.

Potential outputs include:

- BPM;
- key;
- energy curve;
- spectral brightness;
- instrument recognition;
- vocal segments;
- stem separation;
- per-stem MIDI;
- voice texture;
- lyrics/transcription.

Potential future use:

```text
web/metadata evidence
+
audio-grounded profile
+
user behavior
-> better taste hypothesis / curation
```

Do not block the MVP on this integration. If used, prefer offline preprocessing/cache over latency-sensitive runtime analysis.

---

# 12. TTS

Default provider: **MiniMax Speech 2.8 HD**.

Reasoning:

- manual listening test found both MiniMax and ElevenLabs acceptable;
- MiniMax is materially cheaper in the current target region;
- high-quality speech is central to the product.

Keep `TTSProvider` abstract so ElevenLabs or another engine can be A/B tested later.

Narration generation should preserve optional TTS metadata such as:

- pause duration;
- emphasis;
- reflective/energetic style;
- restrained fillers where supported;
- pronunciation hints if needed.

Do not hardcode provider-specific syntax into Writer prompts. Translate generic cues inside the MiniMax adapter.

Generated narration audio should be cached in object storage and referenced by stable IDs/URLs.

---

# 13. Covers

Do not use paid text-to-image APIs in the MVP.

Implement programmatic SVG covers with deterministic seeds.

Potential template families:

- Editorial
- Y2K
- Club Poster
- Archive/Collage-inspired
- Waveform/Data-driven
- Ambient/Gradient

Input may include:

```text
title
subtitle
category
mood
era
genre
seed
optional audio features
```

The same episode should always generate the same cover from the same seed.

Future enhancement: map Ocean Listen features to cover parameters.

Example:

```text
BPM -> repetition/grid density
energy curve -> path shape
brightness -> contrast/luminance
genre -> template family
```

Programmatically overlay title/category text; do not depend on image models to render typography.

---

# 14. Music Provider

Define a stable interface before integrating a real catalog.

Suggested capabilities:

```text
search(query)
resolve_track(track_ref)
get_stream_source(track_ref)
playability(track_ref)
metadata(track_ref)
```

Playback itself may be client-side depending on provider SDK constraints.

The MVP should work with a fake/local/test provider. Do not let missing TME APIs block development.

Expected later adapter:

```text
TMEProvider
```

Core intelligence must not depend on private TME recommendation/history APIs. TME integration should improve catalog availability and playback, not determine whether the product functions.

---

# 15. Recommended implementation stack

## Web

- Next.js
- React
- TypeScript
- Zustand
- SVG cover renderer
- Web Audio API and/or a controlled dual-audio strategy

The player is a core feature; do not blindly delegate it to a generic music-player component if doing so prevents control over segment transitions, crossfades, seeking, and generated frontiers.

## Backend

- Python
- FastAPI
- Pydantic / PydanticAI
- async-first provider adapters

## Persistence

- Postgres
- Redis for ephemeral orchestration primitives / queue / cancellation / pub-sub where helpful
- S3-compatible object storage for generated audio

## Realtime

Prefer SSE for simple one-way episode-state updates unless bidirectional WebSocket behavior is clearly needed.

Potential events:

```text
episode_state_changed
program_skeleton_ready
segment_planned
segment_script_ready
segment_audio_ready
segment_committed
generated_frontier_changed
generation_paused
generation_failed
materialization_complete
```

Do not bind frontend components directly to worker implementation details.

---

# 16. Suggested domain models

These are conceptual; refine with Pydantic/DB models.

## Evidence

```text
id
claim / extracted_text
source_url
source_title
provider
source_type
confidence
retrieved_at
```

## TrackCandidate

```text
canonical_track_ref
artist
title
reasons[]
evidence_ids[]
similarity_dimensions[]
novelty_distance
confidence
availability
```

## ResearchBundle

```text
id
taste_hypotheses[]
evidence[]
candidates[]
open_questions[]
research_cost
```

## ChapterPlan

```text
id
order
track_ref
narrative_role
reason
target_narration_seconds
status
```

## ProgramSkeleton

```text
id
episode_id
thesis
chapters[]
version
created_at
```

## Segment

```text
id
episode_id
chapter_id
kind: MUSIC | NARRATION
order
state
planned_duration
actual_duration
asset_ref / track_ref
committed_at?
played_at?
```

## NarrationScript

```text
text
tts_cues[]
evidence_ids[]
intended_duration_sec
```

## Episode runtime state

```text
playback_position
current_segment_id
committed_frontier
generated_frontier
planning_frontier
generation_mode: PROGRESSIVE | FULL
is_listener_active
last_activity_at
```

---

# 17. Playback design

The frontend should treat the episode as one logical timeline composed of heterogeneous segments.

Example:

```text
0:00-3:42   MUSIC
3:42-4:31   NARRATION
4:31-8:20   MUSIC
8:20-9:03   NARRATION
...
```

Already materialized segments have exact durations. Future segments may only have estimates.

The UI can show an estimated total duration while visually distinguishing the generated portion.

Important playback capabilities:

- pause/resume;
- seek within generated range;
- next chapter;
- previous generated chapter;
- transition music <-> narration;
- future crossfade/ducking support;
- resume state;
- replacement of speculative future chapters without affecting committed segments.

Music/narration mixing may later support behavior such as:

```text
music fades down
narration enters
brief music bed remains
music exits or next track begins
```

For the first vertical slice, correctness matters more than polished mixing.

---

# 18. Cost controls

This project is self-funded.

Rules:

- never fully generate every homepage card;
- expensive generation begins after explicit user engagement;
- progressive materialization should stay only modestly ahead of playback;
- cache research/TTS/materialized episodes;
- limit research loops;
- do not call paid services in unit tests;
- track token/query/character usage per provider;
- make it possible to set development budgets/quotas via configuration;
- stop speculative generation when listener inactivity is detected.

---

# 19. Observability

Instrument from the beginning, even if minimally.

Useful metrics/events:

```text
time_to_first_audio
time_to_first_narration
buffer_ahead_seconds
search_latency
research_latency
writer_latency
tts_latency
provider_error_rate
generation_cost_estimate
episode_start
episode_exit
skip
seek
full_materialize_requested
completion
```

The single most important UX metric early on is probably **time to first audio**.

A second useful metric is whether generation ever falls behind playback.

---

# 20. Repository structure

Suggested starting structure:

```text
repo/
├── AGENTS.md
├── README.md
├── apps/
│   └── web/                     # Next.js
├── services/
│   ├── api/                     # FastAPI entrypoint
│   └── worker/                  # background jobs
├── backend/
│   ├── agents/
│   │   ├── research.py
│   │   ├── curator.py
│   │   ├── writer.py
│   │   └── replanner.py
│   ├── orchestration/
│   │   ├── episode.py
│   │   ├── frontier.py
│   │   └── materializer.py
│   ├── providers/
│   │   ├── llm/
│   │   ├── search/
│   │   ├── tts/
│   │   ├── music/
│   │   └── audio_analysis/
│   ├── models/
│   │   ├── episode.py
│   │   ├── program.py
│   │   ├── research.py
│   │   └── playback.py
│   └── storage/
├── docs/
│   ├── CODEX_HANDOFF.md
│   └── adr/
└── tests/
    ├── evals/
    ├── fixtures/
    └── integration/
```

Use Python `uv` and frontend `pnpm` unless the existing environment strongly favors another standard tool.

## Live-probe startup rule

When an explicitly authorized live probe is requested, start the configured
local music chain before declaring music readiness unavailable: run the local
NetEase-compatible upstream on port `3000`, start the `wavecast-music-dev`
sidecar on port `3101`, then verify `/health` and `/ready`. A stopped local
process is an operational step to fix, not by itself a product or credential
blocker. Stop only when the configured source/API has changed, startup
genuinely fails, or the required credentials/network are actually unavailable.
Keep the probe's existing bounded, no-retry, and cost rules.

For a failed live probe, preserve a sanitized structured report (including the
stage, mapped cause/reason, usage totals, and safe provider-event summaries)
before reporting the failure. Fix routine operational issues autonomously when
they are reversible, such as starting a stopped local service. Ask for a
decision only for missing authority or credentials, destructive actions,
external provider/API changes, or a genuine product/architecture choice.

Do not create unnecessary microservices. `api` and `worker` can share the same Python package/domain code.

---

# 21. Implementation phases

## Phase 0 — Bootstrap and contracts

Goal: establish a clean repository and make future autonomous work safe.

Deliverables:

- monorepo/bootstrap;
- formatting/lint/typecheck/test config;
- `.env.example`;
- typed domain models;
- provider protocols/interfaces;
- episode/segment enums;
- initial state-machine tests;
- basic docs/ADR setup;
- CI pipeline if GitHub Actions is available.

No paid APIs required.

## Phase 1 — Mock vertical slice (highest priority)

Goal: prove the streaming runtime before integrating real AI.

Use:

- FakeSearchProvider;
- FakeLLM/Agent outputs;
- FakeTTSProvider with fixture narration audio;
- Fake/LocalMusicProvider with test tracks;
- in-memory or lightweight DB where sensible, but prefer real Postgres-compatible schemas if setup is cheap.

Required end-to-end flow:

```text
Home card
 -> click
 -> opening track starts immediately
 -> LiveEpisode created
 -> future narration segment becomes ready
 -> player transitions
 -> next track appears
 -> user seeks backward
 -> user cannot seek past generated frontier
 -> user hits next
 -> speculative future can be replaced
 -> user exits
 -> generation stops
 -> user returns and resumes
 -> user requests full materialization
 -> episode becomes MATERIALIZED
```

Acceptance criterion: the runtime semantics work reliably with zero external AI credentials.

## Phase 2 — Real providers

Integrate behind existing interfaces:

- DeepSeek provider;
- Exa discovery provider;
- Tavily research provider;
- optional Serper fallback;
- MusicBrainz;
- Last.fm;
- MiniMax TTS.

Keep mock mode fully operational.

Add usage/cost tracking.

## Phase 3 — Real agent pipeline

Implement bounded agents with structured outputs:

1. Research Agent
2. Curator
3. Writer
4. Replanner

Add evaluation fixtures based on the existing difficult 3rd Coast example.

Initial qualitative golden scenario:

User likes:

```text
3rd Coast — Jealousy
3rd Coast — Luv is True
```

The research/curation pipeline should be able to:

- correctly identify the group/tracks;
- understand the DJMAX context;
- infer a plausible taste profile around smooth female vocals, male rap accents, jazzy/house/R&B/lounge, and 2000s East Asian urban production;
- discover adjacent music beyond merely listing DJMAX artists;
- produce a coherent exploration path with evidence.

Do not hardcode the final recommendation list.

## Phase 4 — Playback polish

Improve:

- music/narration transitions;
- crossfade/ducking;
- generated-frontier visualization;
- buffering/retry behavior;
- cancellation/resume robustness;
- player ergonomics.

## Phase 5 — Product/UI redesign

Only after the core loop is stable, refine:

- Home feed hierarchy;
- cards;
- player visual design;
- procedural cover system;
- chapter presentation;
- "Generate full episode" UX;
- Save/Library;
- mobile responsiveness;
- motion/animation.

## Later / optional

- TME provider;
- share/publish;
- comments/time-coded comments;
- Fork / Remix / "为我重制";
- public discovery feed;
- Ocean Listen integration;
- user taste memory/history;
- offline mode/native app.

---

# 22. Autonomous Codex workflow

The user will not supervise continuously. Work autonomously and keep changes reviewable.

Recommended loop:

```text
read AGENTS.md + handoff
 -> inspect repo/status/tests
 -> pick next milestone task
 -> implement
 -> test/lint/typecheck/build
 -> commit
 -> continue until checkpoint
 -> push feature branch
 -> open PR
 -> write detailed PR summary
```

Do not pause for ordinary implementation preferences.

For large milestones, use feature branches such as:

```text
feature/bootstrap
feature/episode-core
feature/mock-vertical-slice
feature/player
feature/providers
feature/agent-pipeline
```

Use smaller branches if that produces clearer review boundaries.

The user intends to have code reviewed through GitHub. Optimize PRs for reviewability.

PR descriptions should include:

- what was implemented;
- architecture decisions;
- screenshots/recording if UI changed;
- tests run;
- provider calls still mocked;
- migration/config changes;
- known issues;
- recommended next task.

If `gh` is authenticated and there is no remote repository yet, a private GitHub repository may be created as part of bootstrap if the execution environment/user instruction authorizes it. Never create a public repository by default.

---

# 23. First assignment to execute now

Unless the repository already contains meaningful implementation that changes the plan, begin with **Phase 0 + Phase 1**, not real API integrations.

Specifically:

1. Read `AGENTS.md` and this handoff completely.
2. Inspect the repository and preserve anything useful already present.
3. Bootstrap the Next.js + FastAPI project with shared documented development commands.
4. Define the core Pydantic domain models and state enums.
5. Implement `EpisodeOrchestrator` and frontier semantics with tests.
6. Define provider interfaces and fake implementations.
7. Build a minimal Home with mock Episode Seeds.
8. Build the Episode Player with a logical heterogeneous segment timeline.
9. Implement mock progressive generation so future segments become ready over time.
10. Implement backward seek, generated-frontier restriction, next/skip, exit cancellation, resume, and full-materialization behavior.
11. Add integration tests for the complete vertical slice.
12. Run lint/typecheck/tests/build.
13. Commit in coherent steps.
14. Push a feature branch and open a PR with a thorough summary if GitHub access is available.

Do **not** spend Phase 1 time perfecting visual styling or integrating paid AI APIs.

The first milestone should prove that the product's unusual runtime behavior is sound.

---

# 24. Success criteria for the first review

The first PR is successful if a reviewer can run the project locally and observe:

- a Home screen with program cards;
- a card click starts an opening track without waiting for AI;
- a Live Episode begins materializing mock future content;
- the UI shows which range is generated;
- narration and music segments play in sequence;
- the user can seek backward but not into future ungenerated content;
- Next works even if future narration is not ready;
- leaving stops future speculative work;
- returning resumes persisted state;
- "Generate full episode" converts the episode into a complete fixed timeline;
- state-machine/frontier invariants have automated tests;
- no real API keys are required.

Once this passes review, proceed to real provider integration and the actual research/curation/writer pipeline.
