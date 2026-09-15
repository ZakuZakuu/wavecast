# ADR 0005: Normalize real music assets before deterministic radio composition

## Context

Phase 4.1 established browser-driven HTML5 audio playback with deterministic mock WAV
assets. The next slice needs a real catalog-backed music asset and a small radio-style
composition seam without coupling episode runtime state to a vendor SDK or making
narration audio a prerequisite.

## Decision

`MusicProvider` remains the provider boundary. It resolves a `TrackProposal` against
canonical catalog metadata and returns a provider-neutral `AudioAsset` containing an
opaque asset ID, asset type, provider label, playback URL, duration, and safe metadata.
The deterministic `EpisodeComposer` accepts only `ResolvedTrack` identities plus
structured `RadioScript` blocks (`intro`, `track_intro`, `transition`, `outro`). It emits
a `PlayableEpisode` timeline; unresolved proposals raise before any music segment is
created, while narration blocks remain script-ready until a future TTS phase.

Audius is the first external adapter because its catalog and stream endpoints are broad
and low-cost for a demo. Mock mode remains credential-free. In live mode the adapter
keeps the app API key and backend bearer token distinct, and returns a Wavecast playback
proxy URL so a bearer token never reaches browser code. The adapter is replaceable
without exposing Audius fields to episode runtime code.
`MockMusicProvider` remains the default test/local implementation.

Radio block placement is deterministic: opening music may begin immediately, an
unindexed `INTRO` follows that opening track, `TRACK_INTRO(i)` is immediately before
track `i`, and `TRANSITION(i)` fills the gap after track `i` before track `i + 1`.
`OUTRO` follows the final track. Unindexed transitions are compatibility syntax and are
assigned sequentially to available gaps from the first gap.

## Consequences

The browser can receive real music playback URLs through the same segment model used by
mock playback, while server lifecycle/version/frontier semantics remain unchanged. Writer
output is now a structured radio script rather than an article-shaped paragraph. A future
runtime integration can pre-resolve assets through this seam; this milestone does not
add TTS, QQ Music, accounts, recommendations, or a provider-owned playback state machine.
