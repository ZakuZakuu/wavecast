"""Doubao two-voice speech for a researched passage, behind an injectable transport.

The adapter owns what the application needs from a vendor and nothing of the wire: the cache
key and storage of the audio, the usage record for every outcome, the vendor's speed range, and
the error mapping.  *How* the vendor is asked (the podcast WebSocket protocol) is a
:class:`PodcastTransport`, passed in.  No transport for the real service ships yet: the wire
protocol of the fixed-script ("action = 3") mode is not published in a form this repository can
rely on, and it is to be written against a recorded experiment, not guessed.  Until then,
selecting ``doubao`` fails at startup with a clear message (see ``build_dialogue_speech``), and
every test drives the adapter with a fake transport.

The script is sent exactly as written: the vendor must voice the given lines in order, with the
given voice for each speaker, and not add, drop or rewrite words.  A transport that cannot do
that must say so by raising, not by returning other audio.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from wavecast.providers.contracts import AudioAsset, AudioAssetType, ObjectStorageProvider
from wavecast.providers.dialogue_speech import build_dialogue_cache_key
from wavecast.providers.doubao_voices import DOUBAO_PROVIDER_NAME
from wavecast.providers.errors import (
    ProviderConfigurationError,
    ProviderError,
    ProviderInvalidResponseError,
)
from wavecast.providers.speech import SpeechRequest
from wavecast.providers.usage import UsageEvent, UsageLedger

DOUBAO_PODCAST_MODEL = "doubao-podcast"
DOUBAO_PODCAST_PROTOCOL = "doubao-podcast-script-v1"
# Doubao's own speech-rate scale (0 is normal), not MiniMax's 0.9-style multiplier.  The bound
# is only a sanity check on the number; which values the service honours is its own business.
DOUBAO_SPEED_RANGE = (-50.0, 100.0)
SUPPORTED_AUDIO_FORMATS = ("mp3", "wav")
DEFAULT_AUDIO_FORMAT = "mp3"
_CONTENT_TYPES = {"mp3": "audio/mpeg", "wav": "audio/wav"}


@dataclass(frozen=True)
class ScriptLine:
    speaker: str
    voice_id: str
    text: str


@dataclass(frozen=True)
class PodcastScript:
    lines: tuple[ScriptLine, ...]
    speed: float
    audio_format: str


@dataclass(frozen=True)
class PodcastAudio:
    audio: bytes
    audio_format: str
    duration_seconds: float
    # Per-line start/end in seconds, when the vendor reports them.
    line_timings: tuple[tuple[float, float], ...] = ()
    request_id: str | None = None
    billed_characters: int | None = None


class PodcastTransport(Protocol):
    async def synthesize(self, script: PodcastScript) -> PodcastAudio: ...


class DoubaoPodcastSpeechProvider:
    provider_name = DOUBAO_PROVIDER_NAME
    model = DOUBAO_PODCAST_MODEL
    protocol_version = DOUBAO_PODCAST_PROTOCOL

    def __init__(
        self,
        transport: PodcastTransport,
        storage: ObjectStorageProvider,
        *,
        ledger: UsageLedger | None = None,
    ) -> None:
        self._transport = transport
        self._storage = storage
        self._ledger = ledger or UsageLedger()

    def cache_key(self, request: SpeechRequest) -> str:
        audio_format = self._format(request)
        return build_dialogue_cache_key(
            provider=self.provider_name,
            model=self.model,
            request=request,
            protocol_version=self.protocol_version,
            extension=audio_format,
        )

    async def synthesize_dialogue(self, request: SpeechRequest) -> AudioAsset:
        script = self._script(request)
        key = self.cache_key(request)
        started = time.monotonic()
        try:
            result = await self._transport.synthesize(script)
            self._validated(result, script)
        except asyncio.CancelledError:
            self._record(started, script, "cancelled", None)
            raise
        except ProviderError as error:
            self._record(started, script, type(error).__name__, None)
            raise
        except Exception as error:  # noqa: BLE001 - the vendor boundary: map, never leak
            self._record(started, script, "transport_error", None)
            raise ProviderInvalidResponseError("doubao podcast synthesis failed") from error

        duration = max(1, math.ceil(result.duration_seconds))
        timings = [
            {"speaker": line.speaker, "start": round(start, 3), "end": round(end, 3)}
            for line, (start, end) in zip(script.lines, result.line_timings, strict=False)
        ]
        url = await self._storage.put(
            key,
            result.audio,
            _CONTENT_TYPES[result.audio_format],
            metadata={
                "duration_seconds": duration,
                "provider": self.provider_name,
                "turn_timings": timings,
                "voices": [role.model_dump(mode="json") for role in request.roles],
            },
        )
        self._record(started, script, "ok", result)
        return AudioAsset(
            asset_id=key,
            asset_type=AudioAssetType.NARRATION,
            provider=self.provider_name,
            playback_url=url,
            duration=duration,
            metadata={"cache_key": key, "turn_timings": timings, "cache_hit": False},
        )

    @staticmethod
    def _format(request: SpeechRequest) -> str:
        audio_format = request.audio_format or DEFAULT_AUDIO_FORMAT
        if audio_format not in SUPPORTED_AUDIO_FORMATS:
            raise ProviderConfigurationError(f"doubao podcast audio format {audio_format!r} is not supported")
        return audio_format

    def _script(self, request: SpeechRequest) -> PodcastScript:
        if not request.is_dialogue:
            raise ProviderConfigurationError("doubao podcast speech needs a dialogue request")
        speed = 0.0 if request.speed is None else request.speed
        low, high = DOUBAO_SPEED_RANGE
        if not low <= speed <= high:
            raise ProviderConfigurationError(
                f"doubao speech rate must be within {low:g}..{high:g} (Doubao scale, 0 is normal)"
            )
        voices = {role.speaker: role.voice_id for role in request.roles}
        return PodcastScript(
            lines=tuple(
                ScriptLine(turn.speaker.value, voices[turn.speaker], turn.text)
                for turn in request.turns
            ),
            speed=speed,
            audio_format=self._format(request),
        )

    @staticmethod
    def _validated(result: PodcastAudio, script: PodcastScript) -> PodcastAudio:
        if not result.audio:
            raise ProviderInvalidResponseError("doubao podcast returned no audio")
        if result.audio_format != script.audio_format:
            raise ProviderInvalidResponseError("doubao podcast returned a different audio format")
        if not math.isfinite(result.duration_seconds) or result.duration_seconds <= 0:
            raise ProviderInvalidResponseError("doubao podcast returned no usable duration")
        timings: Sequence[tuple[float, float]] = result.line_timings
        if timings and len(timings) != len(script.lines):
            raise ProviderInvalidResponseError("doubao podcast timings do not match the script")
        return result

    def _record(
        self, started: float, script: PodcastScript, outcome: str, result: PodcastAudio | None
    ) -> None:
        sent = sum(len(line.text) for line in script.lines)
        metadata: dict[str, Any] = {
            "outcome": outcome,
            "turns": len(script.lines),
            "model": self.model,
            "protocol": self.protocol_version,
        }
        billed = result.billed_characters if result is not None else None
        self._ledger.record(
            UsageEvent(
                provider=self.provider_name,
                operation="dialogue_speech",
                request_id=result.request_id if result is not None else None,
                elapsed_ms=int((time.monotonic() - started) * 1000),
                # What the vendor billed when it says so; otherwise what was sent (a count of the
                # script, not a guess of the price - there is no price table for this service).
                usage_characters=billed if billed is not None else sent,
                metadata=metadata,
            )
        )


__all__ = [
    "DEFAULT_AUDIO_FORMAT",
    "DOUBAO_PODCAST_MODEL",
    "DOUBAO_PODCAST_PROTOCOL",
    "DOUBAO_SPEED_RANGE",
    "DoubaoPodcastSpeechProvider",
    "PodcastAudio",
    "PodcastScript",
    "PodcastTransport",
    "ScriptLine",
]
