# ADR 0006: Deterministic multi-provider music retrieval

## Context

Phase 4.2 established a provider-neutral `MusicProvider` boundary and an Audius
adapter. A single catalog is not sufficient for reliable long-tail discovery or
playback fallback, but editorial intelligence and episode runtime must not become
coupled to vendor APIs.

## Decision

Keep the existing `MusicProvider` contract unchanged:

```text
search(query, limit)
resolve_track(track_ref)
get_playback_asset(resolved_track)
```

`MusicProviderRegistry` owns provider-name and provider-prefix lookup, ordered
search preference, and playback routing for qualified references such as
`netease:<id>`, `qqmusic:<id>`, and `audius:<id>`. `MusicRetrievalService` fans
out searches concurrently with a bounded timeout per provider, normalizes
provenance, isolates failures, groups equivalent recording/version identities,
and ranks results with explicit deterministic reasons.

The retrieval layer uses `RetrievedTrack` and conservative `VersionKind` values.
It never infers `STUDIO` from an absent suffix. Explicit live, remix, acoustic,
OST, or radio-edit evidence remains distinct; equivalent source alternatives are
kept within one group for later playback fallback.

NetEase Cloud Music and QQ Music are experimental HTTP sidecar adapters. They use
the same small configurable JSON contract and base URLs (`NETEASE_MUSIC_API_BASE_URL`
and `QQ_MUSIC_API_BASE_URL`); WaveCast does not embed reverse-engineered platform
protocols. A local deployment may adapt
[`NeteaseCloudMusicApiEnhanced/api-enhanced`](https://github.com/neteasecloudmusicapienhanced/api-enhanced)
or [`L-1124/QQMusicApi`](https://github.com/L-1124/QQMusicApi) to that contract. The
sidecars are optional and never required by mock mode or CI.

Proposal resolution remains deterministic application code. The ensemble resolver
accepts a `TrackProposal`, requires exact canonical artist/title identity and a
provider-qualified playable reference, then returns `ResolvedTrack`. LLM-facing
schemas and `EpisodeComposer` remain unchanged.

An opt-in metadata-only probe exists for manually configured sidecars. It prints
normalized query/provider/artist/title/version/playability/timing fields only and
is never run by CI.

## Consequences

WaveCast can compare and retain catalog alternatives without changing editorial
prompts, search budgets, playback state, or episode composition. A provider that
times out or returns malformed data no longer prevents other catalogs from
contributing results. Sidecar availability and their normalized HTTP response
contract remain operational concerns for a later live integration.
