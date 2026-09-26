# ADR 0019: Capability-level production provider gates

## Context

WaveCast originally used `WAVECAST_PROVIDER_MODE` as one coarse switch for the
whole provider graph. That is convenient for credential-free development, but it
is too risky for the first hosted live rollout: enabling one real capability
would also construct unrelated paid adapters and make failures harder to isolate.

The hosted product has already proven the independently gated recommendation
planner. The remaining proposal, music, progressive intelligence, and TTS
boundaries need the same operational property without replacing the global mock
safety default.

## Decision

Keep `WAVECAST_PROVIDER_MODE` as the inherited default, and add explicit
capability selectors:

- `WAVECAST_PROPOSAL_PLANNER=inherit|mock|deepseek`
- `WAVECAST_MUSIC_PROVIDER=inherit|mock|auto|netease|qqmusic|audius`
- `WAVECAST_FAST_START_PROVIDER=inherit|mock|deepseek`
- `WAVECAST_RESEARCH_PROVIDER=inherit|mock|live`
- `WAVECAST_CURATOR_PROVIDER=inherit|mock|deepseek`
- `WAVECAST_WRITER_PROVIDER=inherit|mock|deepseek`
- `WAVECAST_TTS_PROVIDER=inherit|mock|minimax`

`inherit` preserves the old behavior: global mock resolves every capability to
mock; global live resolves the established live graph. An explicit live selector
creates live-scoped provider settings only at that boundary, so global mock can
remain the production safety default while selected capabilities are activated.

A configured live capability fails closed when its required credential or music
endpoint is missing. It must not silently fall back to a mock sibling after the
listener has crossed a paid/live commit point. Recommendation inventory keeps its
existing independent selector and deterministic provider-failure fallback.

The default MiniMax presentation profile for newly generated narration becomes
`speech-2.8-turbo` at speed `0.8`; environment variables can still override
both values.

## Consequences

Production can deploy the full wiring once, then activate and roll back live
boundaries through Railway variables without a code change for every step.
Ordinary CI and local development remain credential-free under global mock.

The selectors are operational routing, not new domain states. Episode lifecycle,
frontier semantics, provider interfaces, and persisted episode schemas do not
change.

A recommendation-derived Program Proposal keeps the recommendation's public
title, description, and tags while the proposal capability is still mock. Mock
opening-track identities remain usable by the local runtime but are hidden from
public card/detail artist previews until real music resolution is enabled.
