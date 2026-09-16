# ADR 0010: Treat chapters as narrative beats with optional music

## Context

Curator plans were previously shaped as a list of tracks, which made a
contextual story beat impossible unless it also carried a playable catalog
identity.  Resolution can also remove an optional track while the surrounding
narrative remains useful.  In addition, the visible editorial copy is not
always the best pronunciation for a speech provider, and a fixed short
narration length does not scale with the proposed program duration.

## Decision

`ChapterPlan` is a narrative beat.  Its `track` is optional, and an unresolved
or absent track removes only the music asset; the chapter still goes through
Writer.  The composer accepts zero or one resolved music asset for a chapter
and never promotes a `TrackProposal` into the timeline.  A complete episode
still requires the existing minimum of two resolved playable tracks.

The assembly service allocates a bounded spoken budget per chapter using a
configurable default ratio of 15% of the requested duration (constrained to the
10–20% policy range).  Writer receives the resulting target duration rather
than relying on a generic “concise” instruction.

Requests carry an explicit `output_language` (`auto`, `zh-CN`, `en-US`, or
`ja-JP`).  `auto` is resolved deterministically from the user topic and the
selected language is passed through FastStart, Curator, and Writer; catalog
artist/title strings are never used for language inference.

`RadioScriptBlock.text` remains the visible/editorial text.  An optional
`tts_text` contains pronunciation-aware speech text, for example displaying
`3rd Coast` while synthesizing `Third Coast`.  Materialization uses
`tts_text` when present, so its cache identity changes with the synthesized
text while UI and diagnostics continue to use the visible copy.  Cue handling
remains provider-neutral and bounded by the existing renderer.

## Alternatives considered

- Require every chapter to resolve to music: rejected because narrative
  context can be valuable without another song and resolution may legitimately
  fail for an optional proposal.
- Rewrite visible text for TTS: rejected because it degrades editorial display
  and makes cache identity difficult to reason about.
- Use a fixed narration duration: rejected because a 30-minute proposal needs
  more spoken context than a two-minute program.
- Infer language from artist/title metadata: rejected because it is unstable
  and would produce incorrect language choices for multilingual topics.

## Consequences

The intelligence model can represent narrative-first programs without weakening
the proposal → catalog resolution → playable timeline boundary.  Writer and
materialization tests must cover both visible and synthesized text.  Future
style controls can replace the default narration policy without changing
chapter or playback semantics.
