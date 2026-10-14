"""Speaking a two-host passage: the provider contract, the cache key, and a credential-free fake.

A passage is voiced as *one* audio asset.  The cache key covers everything that decides what the
listener hears - the ordered turns, which voice speaks which host, the vendor and model, the
speed, the format and the protocol version - so a changed voice mapping or a changed word never
reuses old audio, and an unchanged passage never pays for synthesis twice.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from typing import Protocol

from wavecast.providers.contracts import AudioAsset, AudioAssetType, ObjectStorageProvider
from wavecast.providers.errors import ProviderError
from wavecast.providers.speech import SpeechRequest

DIALOGUE_PROTOCOL_VERSION = "dialogue-audio-v1"
FAKE_CHARS_PER_SECOND = 6.0


class DialogueSpeechProvider(Protocol):
    provider_name: str
    model: str

    def cache_key(self, request: SpeechRequest) -> str: ...

    async def synthesize_dialogue(self, request: SpeechRequest) -> AudioAsset: ...


def build_dialogue_cache_key(
    *,
    provider: str,
    model: str,
    request: SpeechRequest,
    protocol_version: str = DIALOGUE_PROTOCOL_VERSION,
    extension: str = "mp3",
) -> str:
    if not request.is_dialogue:
        raise ValueError("a dialogue cache key needs a dialogue request")
    payload = {
        "provider": provider,
        "model": model,
        "protocol": protocol_version,
        "turns": [[turn.speaker.value, turn.text] for turn in request.turns],
        "roles": sorted([role.speaker.value, role.voice_id] for role in request.roles),
        "speed": request.speed,
        "audio_format": request.audio_format,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"dialogue-{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}.{extension}"


class MockDialogueSpeechProvider:
    """Deterministic fake: silent WAV whose length follows the text (or a fixed length).

    ``fixed_duration_seconds`` stands in for an existing recording of known length.  It records
    every synthesis, can be made to fail, and stores audio with the same ``duration_seconds``
    metadata convention the real TTS adapters use, so cache hits work the same way.
    """

    provider_name = "mock-dialogue-speech"
    model = "mock-dialogue"

    def __init__(
        self,
        storage: ObjectStorageProvider,
        *,
        fixed_duration_seconds: int | None = None,
        delay_seconds: float = 0.0,
    ) -> None:
        self.storage = storage
        self.fixed_duration_seconds = fixed_duration_seconds
        self.delay_seconds = delay_seconds
        self.calls = 0
        self.requests: list[SpeechRequest] = []
        self.fail_with: ProviderError | None = None

    def cache_key(self, request: SpeechRequest) -> str:
        return build_dialogue_cache_key(
            provider=self.provider_name, model=self.model, request=request, extension="wav"
        )

    async def synthesize_dialogue(self, request: SpeechRequest) -> AudioAsset:
        self.calls += 1
        self.requests.append(request)
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if self.fail_with is not None:
            raise self.fail_with
        key = self.cache_key(request)
        characters = sum(len(turn.text) for turn in request.turns)
        duration = self.fixed_duration_seconds or max(
            1, min(300, math.ceil(characters / FAKE_CHARS_PER_SECOND))
        )
        timings = _turn_timings(request, duration)
        url = await self.storage.put(
            key,
            _silent_wav(duration),
            "audio/wav",
            metadata={
                "duration_seconds": duration,
                "provider": self.provider_name,
                "turn_timings": timings,
                "voices": [role.model_dump(mode="json") for role in request.roles],
            },
        )
        return AudioAsset(
            asset_id=key,
            asset_type=AudioAssetType.NARRATION,
            provider=self.provider_name,
            playback_url=url,
            duration=duration,
            metadata={"cache_key": key, "turn_timings": timings, "cache_hit": False},
        )


def _turn_timings(request: SpeechRequest, duration: int) -> list[dict[str, object]]:
    total = sum(len(turn.text) for turn in request.turns) or 1
    cursor = 0.0
    timings: list[dict[str, object]] = []
    for turn in request.turns:
        span = duration * len(turn.text) / total
        timings.append(
            {"speaker": turn.speaker.value, "start": round(cursor, 3), "end": round(cursor + span, 3)}
        )
        cursor += span
    return timings


def _silent_wav(duration_seconds: int) -> bytes:
    import wave
    from io import BytesIO

    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(1)
        wav.setframerate(8000)
        wav.writeframes(b"\x80" * (8000 * duration_seconds))
    return buffer.getvalue()
