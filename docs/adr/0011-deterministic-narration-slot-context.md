# ADR 0011: Derive Writer narration slots from resolved playback adjacency

## Context

Curator chapter indices are narrative ordering hints, not stable playback
identifiers. Resolution can remove a proposed track while retaining its
narrative chapter, so a Writer that receives only chapter numbers or a prose
`next_track_metadata` string can refer to the wrong song. Numeric anchors in a
structured Writer response can also be silently discarded during normalization.

## Decision

After chapter selection and catalog resolution, assembly normalizes the
application-visible chapter sequence to contiguous indices and derives one or
more typed `NarrationSlotContext` values for each chapter. Each context
describes one real slot in final playback order: before a track, after the
current track, or after the final track. It contains only the exact resolved
tracks adjacent to that slot and an allowlist of Writer block kinds valid there.
For example, a middle track-bearing chapter gets separate contexts for its
`TRACK_INTRO` (previous -> current) and `TRANSITION` (current -> next).

Writer receives those slot contexts for editorial adjacency. It may return
ordered narration blocks, but application code strips/ignores numeric playback
placement and matches each block to a typed allowed slot before assigning the
final anchor. Every non-empty parsed block must receive a valid placement; an
impossible placement raises a typed assembly normalization error. Diagnostic
output calls the post-Writer, provider-index-stripped models `parsed_blocks`
and separately exposes the normalized blocks and slot contexts; it does not
claim to contain a raw provider payload.

## Consequences

Unresolved middle chapters can speak about the actual preceding and upcoming
playable tracks, and trailing narrative beats remain after the final track.
Multiple spoken blocks in one gap retain their order, while duplicate final
`OUTRO` blocks are converted to audible final-gap transitions after the first
outro.
The Composer continues to consume its existing internal `RadioScriptBlock`
anchors, preserving immediate opening music and existing timeline semantics.
Legacy direct Composer/normalization callers remain supported, but the live
assembly path no longer relies on Writer-authored numeric indices or silent
fallback drops.
