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

    profile_id: str = "adaptive-v2"
    version: int = Field(default=2, ge=1)
    speed: float = Field(ge=0.5, le=2.0)
    language_boost: str | None = None


class SpeechDirector:
    """Pure policy: start from one baseline and make only small role/text adjustments."""

    DEFAULT_BASE_SPEED = 0.80
    MIN_SPEED = 0.50
    MAX_SPEED = 2.00
    MIXED_SCRIPT_DELTA = 0.02
    _ROLE_SPEED_DELTAS = {
        NarrationRole.INTRO: 0.00,
        NarrationRole.TRACK_INTRO: 0.02,
        NarrationRole.TRANSITION: 0.00,
        NarrationRole.OUTRO: -0.02,
        NarrationRole.GENERAL: 0.00,
    }

    @classmethod
    def profile_for(
        cls,
        role: NarrationRole,
        rendered_text: str,
        *,
        baseline_speed: float | None = None,
    ) -> SpeechProfile:
        baseline = cls.DEFAULT_BASE_SPEED if baseline_speed is None else baseline_speed
        speed = baseline + cls._ROLE_SPEED_DELTAS[role]
        if _CJK_RE.search(rendered_text) and _LATIN_RE.search(rendered_text):
            speed -= cls.MIXED_SCRIPT_DELTA
        speed = min(cls.MAX_SPEED, max(cls.MIN_SPEED, speed))
        return SpeechProfile(speed=round(speed, 3))
