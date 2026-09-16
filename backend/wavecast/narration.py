"""Provider-neutral narration cue rendering.

LLM output contains semantic cues only.  This module owns the small allowlist and
renders stable MiniMax-compatible text without ever interpolating unknown cue values.
"""

from __future__ import annotations

from dataclasses import dataclass

CUE_RENDERING_VERSION = "wavecast-cues-v2"
CUE_TAGS: dict[str, str] = {
    "pause_short": "<#0.25#>",
    "pause_medium": "<#0.50#>",
    "pause_long": "<#0.90#>",
    "breath": "(breath)",
}


@dataclass(frozen=True)
class RenderedNarration:
    text: str
    recognized_cues: tuple[str, ...]
    rendering_version: str = CUE_RENDERING_VERSION


def render_narration(text: str, cues: list[str]) -> RenderedNarration:
    """Render only cues whose position is safe without block-level semantics.

    Pause markers require positions between speakable text spans.  Radio script
    blocks currently carry only an unordered cue allowlist, so retain pause cues
    for cache identity but do not emit them into MiniMax text.  ``breath`` is a
    provider-supported interjection and is safe as a single trailing annotation.
    """
    normalized_text = text.strip()
    recognized = tuple(cue for cue in cues if cue in CUE_TAGS)
    tags = [CUE_TAGS[cue] for cue in recognized if cue == "breath"]
    rendered = " ".join([normalized_text, *tags]) if tags else normalized_text
    return RenderedNarration(rendered, recognized)
