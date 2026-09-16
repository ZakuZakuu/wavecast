"""Provider-neutral narration cue rendering.

LLM output contains semantic cues only.  This module owns the small allowlist and
renders stable MiniMax-compatible text without ever interpolating unknown cue values.
"""

from __future__ import annotations

from dataclasses import dataclass

CUE_RENDERING_VERSION = "wavecast-cues-v1"
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
    """Append only recognized restrained cues to the narration text."""
    normalized_text = text.strip()
    recognized = tuple(cue for cue in cues if cue in CUE_TAGS)
    tags = [CUE_TAGS[cue] for cue in recognized]
    rendered = " ".join([normalized_text, *tags]) if tags else normalized_text
    return RenderedNarration(rendered, recognized)
