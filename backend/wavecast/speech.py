"""Deterministic, provider-neutral speaking policy for narration materialization."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field

from wavecast.models.episode import NarrationRole

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_LATIN_RE = re.compile(r"[A-Za-z]")


class SpeechProfile(BaseModel):
    """Small provider-neutral description of how one narration should sound."""

    model_config = ConfigDict(frozen=True)

    profile_id: str = "adaptive-v1"
    version: int = Field(default=1, ge=1)
    speed: float = Field(ge=0.85, le=0.96)
    language_boost: str | None = None


class SpeechDirector:
    """Pure policy: role and a tiny mixed-script signal choose a bounded profile."""

    MIN_SPEED = 0.85
    MAX_SPEED = 0.96
    MIXED_SCRIPT_DELTA = 0.03
    _ROLE_SPEEDS = {
        NarrationRole.INTRO: 0.90,
        NarrationRole.TRACK_INTRO: 0.92,
        NarrationRole.TRANSITION: 0.90,
        NarrationRole.OUTRO: 0.88,
        NarrationRole.GENERAL: 0.90,
    }

    @classmethod
    def profile_for(cls, role: NarrationRole, rendered_text: str) -> SpeechProfile:
        speed = cls._ROLE_SPEEDS[role]
        if _CJK_RE.search(rendered_text) and _LATIN_RE.search(rendered_text):
            speed -= cls.MIXED_SCRIPT_DELTA
        speed = min(cls.MAX_SPEED, max(cls.MIN_SPEED, speed))
        return SpeechProfile(speed=speed)
