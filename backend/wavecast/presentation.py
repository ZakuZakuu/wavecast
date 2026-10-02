from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class HostMode(StrEnum):
    NONE = "NONE"
    LIGHT = "LIGHT"
    FULL = "FULL"


class OpeningStrategy(StrEnum):
    FULL_TRACK = "FULL_TRACK"
    OPPORTUNISTIC = "OPPORTUNISTIC"
    EARLY_BRIDGE = "EARLY_BRIDGE"


class TransitionStyle(StrEnum):
    CLEAN = "CLEAN"
    RADIO = "RADIO"
    DJ = "DJ"


class PresentationIntent(BaseModel):
    """High-level listening presentation policy, separate from track selection."""

    model_config = ConfigDict(frozen=True)

    host_mode: HostMode = HostMode.LIGHT
    opening_strategy: OpeningStrategy = OpeningStrategy.OPPORTUNISTIC
    transition_style: TransitionStyle = TransitionStyle.RADIO


def infer_presentation_intent(text: str) -> PresentationIntent:
    """Infer conservative presentation policy from an explicit listener request.

    This first pass deliberately reacts only to strong wording. Ambiguous requests
    keep the WaveCast defaults so track/route generation remains independent from
    presentation mechanics.
    """

    normalized = " ".join(text.casefold().split())

    host_none = (
        "纯音乐",
        "只听歌",
        "只放歌",
        "不要旁白",
        "不需要旁白",
        "无旁白",
        "不要主持",
        "不需要主持",
        "不要解说",
        "music only",
        "no narration",
        "no host",
        "without commentary",
    )
    host_full = (
        "主持讲解",
        "详细讲解",
        "多讲一点",
        "多讲点",
        "带我了解",
        "电台主持",
        "guided listening",
        "radio host",
        "with commentary",
    )

    full_track = (
        "完整播放",
        "完整听",
        "整首",
        "不要截歌",
        "不要切歌",
        "full track",
        "whole song",
        "play the whole",
    )
    early_bridge = (
        "快速探索",
        "快速逛",
        "速览",
        "快速过一遍",
        "快节奏探索",
        "quick tour",
        "rapid discovery",
        "sampler",
    )

    clean_transition = (
        "不要混音",
        "不要crossfade",
        "不要 crossfade",
        "简单衔接",
        "clean transition",
        "no crossfade",
    )
    dj_transition = (
        "dj mix",
        "dj模式",
        "dj 模式",
        "串烧",
        "beat mix",
        "beatmatch",
        "beat match",
    )

    if any(token in normalized for token in host_none):
        host_mode = HostMode.NONE
    elif any(token in normalized for token in host_full):
        host_mode = HostMode.FULL
    else:
        host_mode = HostMode.LIGHT

    if any(token in normalized for token in full_track):
        opening_strategy = OpeningStrategy.FULL_TRACK
    elif any(token in normalized for token in early_bridge):
        opening_strategy = OpeningStrategy.EARLY_BRIDGE
    else:
        opening_strategy = OpeningStrategy.OPPORTUNISTIC

    if any(token in normalized for token in clean_transition):
        transition_style = TransitionStyle.CLEAN
    elif any(token in normalized for token in dj_transition):
        transition_style = TransitionStyle.DJ
    else:
        transition_style = TransitionStyle.RADIO

    return PresentationIntent(
        host_mode=host_mode,
        opening_strategy=opening_strategy,
        transition_style=transition_style,
    )


def narration_ratio_for_host_mode(
    mode: HostMode,
    *,
    full_ratio: float = 0.15,
) -> float:
    """Map host density to a deterministic spoken-time target."""

    if not 0 <= full_ratio <= 1:
        raise ValueError("full narration ratio must be between 0 and 1")
    if mode is HostMode.NONE:
        return 0.0
    if mode is HostMode.LIGHT:
        # Keep LIGHT materially quieter than FULL while preserving enough room
        # for a useful first bridge and final outro.
        return min(full_ratio, max(0.04, full_ratio * 0.55))
    return full_ratio


def host_mode_prompt_guidance(mode: HostMode) -> str:
    if mode is HostMode.NONE:
        return "No host narration should be authored."
    if mode is HostMode.LIGHT:
        return (
            "LIGHT host mode: speak only when the transition adds real listening value. "
            "Prefer one compact editorial action, usually about 8-18 seconds, and stop "
            "instead of filling the budget."
        )
    return (
        "FULL host mode: provide a guided-listening explanation when evidence supports it. "
        "A useful block is usually about 20-35 seconds, but still stop when the editorial "
        "action is complete."
    )
