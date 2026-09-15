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

Audius is the first read-only external adapter because its catalog and stream endpoints
are broad and low-cost for a demo. It is optional, has no required credential in mock
mode, and is replaceable without exposing Audius fields to episode runtime code.
`MockMusicProvider` remains the default test/local implementation.

## Consequences

The browser can receive real music playback URLs through the same segment model used by
mock playback, while server lifecycle/version/frontier semantics remain unchanged. Writer
output is now a structured radio script rather than an article-shaped paragraph. A future
runtime integration can pre-resolve assets through this seam; this milestone does not
add TTS, QQ Music, accounts, recommendations, or a provider-owned playback state machine.
