"""Stable cache-key construction shared by TTS adapters and materialization."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def build_tts_cache_key(
    *,
    provider: str,
    model: str,
    voice_id: str,
    speed: float,
    language_boost: str,
    audio_settings: dict[str, Any],
    rendered_text: str,
    recognized_cues: list[str] | tuple[str, ...],
    rendering_version: str,
    extension: str = "mp3",
) -> str:
    payload = {
        "provider": provider,
        "model": model,
        "voice_id": voice_id,
        "speed": speed,
        "language_boost": language_boost,
        "audio_settings": audio_settings,
        "rendered_text": rendered_text,
        "recognized_cues": list(recognized_cues),
        "rendering_version": rendering_version,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{digest}.{extension.lstrip('.')}"
