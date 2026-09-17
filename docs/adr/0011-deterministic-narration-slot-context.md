# ADR 0011: Derive Writer narration slots from resolved playback adjacency

## Context

Curator chapter indices are narrative ordering hints, not stable playback
identifiers. Resolution can remove a proposed track while retaining its
narrative chapter, so a Writer that receives only chapter numbers or a prose
`next_track_metadata` string can refer to the wrong song. Numeric anchors in a
structured Writer response can also be silently discarded during normalization.

## Decision

After chapter selection and catalog resolution, assembly normalizes the
application-visible chapter sequence to contiguous indices and derives a typed
`NarrationSlotContext` for every chapter. The context contains the chapter's
resolved track (if any), the nearest playable track just heard, the nearest
playable track coming next, and opening/final-boundary flags.

Writer receives that resolved context for editorial adjacency. It may return
ordered narration blocks, but application code strips/ignores numeric playback
placement and deterministically assigns each block to its chapter slot. Every
non-empty parsed block must receive a valid placement; an impossible placement
raises a typed assembly normalization error. The final result exposes only
parsed/normalized Writer models and safe per-chapter counts in the opt-in probe.

## Consequences

Unresolved middle chapters can speak about the actual preceding and upcoming
playable tracks, and trailing narrative beats remain after the final track.
The Composer continues to consume its existing internal `RadioScriptBlock`
anchors, preserving immediate opening music and existing timeline semantics.
Legacy direct Composer/normalization callers remain supported, but the live
assembly path no longer relies on Writer-authored numeric indices or silent
fallback drops.
