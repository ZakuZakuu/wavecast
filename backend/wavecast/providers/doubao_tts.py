"""Doubao's ordinary single-voice speech for the host's opening, bridges and outro.

The two-host passages keep the podcast model (``doubao_podcast``); this is the one-voice
counterpart behind the same ``TTSProvider`` contract the narration materializer already uses.

Verified, and therefore all that is offered: ``POST /api/v3/tts/unidirectional`` with ``X-Api-Key``
and the ``seed-tts-2.0`` resource, the voice ``zh_male_liufei_uranus_bigtts``, 24 kHz mono 16-bit
PCM, speech rate 0, and ``X-Control-Require-Usage-Tokens-Return: *`` so the service reports the
characters it bills (``usage.text_words``).  The reply is a stream of JSON objects: ``code`` 0 with
a base64 audio chunk, then ``code`` 20000000 as the end.  HTTP 200 alone is not completion; a
reply that does not end with the end code is rejected and nothing is stored.

The adapter owns: the speech-rate scale (WaveCast's ``SpeechProfile.speed`` is a multiplier around
1.0, Doubao's rate is 0 for normal speed), the cache key (vendor, model, voice, rate and every
audio parameter, so MiniMax audio is never reused), a local WAV container around the PCM, the
error mapping, and **exactly one final usage event per attempt** - whether it succeeded, the
service failed, the reply did not pass the checks, storing failed, or the caller cancelled.
There is no retry and no fallback to another voice.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import io
import json
import math
import wave
from time import perf_counter
from typing import Any

import httpx

from wavecast.narration import CUE_RENDERING_VERSION, CUE_TAGS
from wavecast.providers.config import ProviderSettings
from wavecast.providers.contracts import AudioAsset, AudioAssetType, ObjectStorageProvider
from wavecast.providers.errors import (
    ProviderError,
    ProviderIncompleteResponseError,
    ProviderInvalidResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from wavecast.providers.http import normalize_http_error
from wavecast.providers.tts_cache import build_tts_cache_key
from wavecast.providers.usage import UsageEvent, UsageLedger
from wavecast.speech import SpeechProfile

DOUBAO_TTS_PROVIDER_NAME = "doubao_tts"
DOUBAO_TTS_ENDPOINT = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
DOUBAO_TTS_RESOURCE_ID = "seed-tts-2.0"
DOUBAO_TTS_PROTOCOL = "doubao-tts-unidirectional-pcm24k-v1"
SAMPLE_RATE = 24000
BYTES_PER_SECOND = SAMPLE_RATE * 2
END_CODE = 20000000
# Doubao's rate scale: 0 is normal speed, -50 is 0.5x and 100 is 2x.
MIN_SPEECH_RATE, MAX_SPEECH_RATE = -50, 100
# Local guard against a runaway reply; not a limit of the service.
MAX_AUDIO_SECONDS = 180.0

# Published rate (CNY per 10,000 characters) as the user gave it on 2026-10-16.  Bump the
# version when it changes.
PRICE_VERSION = "doubao-tts-2026-10-16"
CNY_PER_TEN_THOUSAND_CHARACTERS = 3.0

_AUDIO_SETTINGS = {
    "container": "wav",
    "encoding": "pcm_s16le",
    "sample_rate": SAMPLE_RATE,
    "channels": 1,
    "protocol": DOUBAO_TTS_PROTOCOL,
}


def speech_rate_for(profile: SpeechProfile | None) -> int:
    """Doubao's rate for a WaveCast speed multiplier: 1.0 -> 0, 0.5 -> -50, 2.0 -> 100."""

    if profile is None:
        return 0
    return max(MIN_SPEECH_RATE, min(MAX_SPEECH_RATE, round((profile.speed - 1.0) * 100)))


def price_for(billed_characters: int | None) -> dict[str, Any]:
    """The cost from the characters the service reported.  Missing is unknown, a reported 0 is 0."""

    if billed_characters is None:
        cost, basis = None, "usage_missing"
    else:
        cost = round(billed_characters * CNY_PER_TEN_THOUSAND_CHARACTERS / 10_000, 8)
        basis = "reported_text_words"
    return {
        "estimated_cost_cny": cost,
        "estimated_cost_cny_low": cost,
        "estimated_cost_cny_high": cost,
        "cost_basis": basis,
        "price_version": PRICE_VERSION,
    }


class DoubaoTTSProvider:
    provider_name = DOUBAO_TTS_PROVIDER_NAME
    model = DOUBAO_TTS_RESOURCE_ID
    protocol_version = DOUBAO_TTS_PROTOCOL
    # WaveCast's speed multiplier at which Doubao speaks at its normal rate (its rate 0).
    speech_speed_baseline = 1.0

    def __init__(
        self,
        settings: ProviderSettings,
        *,
        storage: ObjectStorageProvider,
        ledger: UsageLedger | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.ledger = ledger or UsageLedger()
        self.client = client or httpx.AsyncClient(timeout=settings.timeout_seconds)
        self._owns_client = client is None
        self._locks: dict[str, asyncio.Lock] = {}

    @property
    def voice_id(self) -> str:
        return self.settings.doubao_tts_voice_id

    def cache_key(
        self,
        rendered_text: str,
        cues: list[str] | tuple[str, ...],
        *,
        profile: SpeechProfile | None = None,
    ) -> str:
        return build_tts_cache_key(
            provider=self.provider_name,
            model=self.model,
            voice_id=self.voice_id,
            speed=float(speech_rate_for(profile)),  # Doubao's scale; never comparable with MiniMax's
            language_boost="",
            audio_settings=dict(_AUDIO_SETTINGS),
            rendered_text=rendered_text,
            recognized_cues=cues,
            rendering_version=CUE_RENDERING_VERSION,
            extension="wav",
        )

    async def synthesize(
        self, text: str, *, cues: list[str], profile: SpeechProfile | None = None
    ) -> AudioAsset:
        api_key = self.settings.credential_for("doubao_tts")  # not an attempt if it cannot be made
        spoken = _spoken(text)
        if not spoken:
            raise ProviderInvalidResponseError("doubao tts has nothing to speak")
        rate = speech_rate_for(profile)
        key = self.cache_key(text, cues, profile=profile)
        async with self._locks.setdefault(key, asyncio.Lock()):
            started = perf_counter()
            cached = await self.storage.get(key)
            duration = _stored_duration(cached.metadata) if cached is not None else None
            if cached is not None and duration is not None:
                self._record(started, spoken, rate, "ok", cache_hit=True)
                return self._asset(key, duration, cached.metadata.get("billed_characters"), cache_hit=True)
            return await self._attempt(key, spoken, rate, api_key, started)

    async def _attempt(
        self, key: str, spoken: str, rate: int, api_key: str, started: float
    ) -> AudioAsset:
        outcome, stage = "error", "request"
        billed: int | None = None
        audio_seconds: float | None = None
        try:
            pcm, billed = await self._request(spoken, rate, api_key)
            stage = "validate"
            audio_seconds = _validated_seconds(pcm)
            stage = "store"
            duration = max(1, math.floor(audio_seconds + 0.5))
            url = await self.storage.put(
                key,
                _wav(pcm),
                "audio/wav",
                metadata={
                    "duration_seconds": duration,
                    "provider": self.provider_name,
                    "model": self.model,
                    "voice_id": self.voice_id,
                    "speech_rate": rate,
                    "billed_characters": billed,
                },
            )
            outcome = "ok"
            return self._asset(key, duration, billed, cache_hit=False, url=url)
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        except ProviderError as error:
            outcome = type(error).__name__
            raise
        except Exception as error:  # noqa: BLE001 - the vendor boundary: map, never leak
            outcome = "storage_error" if stage == "store" else "transport_error"
            raise ProviderInvalidResponseError("doubao tts synthesis failed") from error
        finally:
            self._record(
                started, spoken, rate, outcome, cache_hit=False,
                billed=billed, stage=stage, audio_seconds=audio_seconds,
            )

    async def _request(self, spoken: str, rate: int, api_key: str) -> tuple[bytes, int | None]:
        headers = {
            "X-Api-Key": api_key,
            "X-Api-Resource-Id": self.model,
            "X-Control-Require-Usage-Tokens-Return": "*",
            "Content-Type": "application/json",
        }
        body = {
            "user": {"uid": "wavecast"},
            "req_params": {
                "text": spoken,
                "speaker": self.voice_id,
                "audio_params": {"format": "pcm", "sample_rate": SAMPLE_RATE, "speech_rate": rate},
            },
        }
        try:
            response = await self.client.post(
                DOUBAO_TTS_ENDPOINT, headers=headers, json=body, timeout=self.settings.timeout_seconds
            )
        except httpx.TimeoutException as error:
            raise ProviderTimeoutError("doubao tts timed out") from error
        except httpx.RequestError as error:
            raise ProviderUnavailableError("doubao tts transport failed") from error
        if response.is_error:
            raise normalize_http_error(self.provider_name, response.status_code, "")
        return _parse_stream(response.content)

    def _asset(
        self,
        key: str,
        duration: int,
        billed: object,
        *,
        cache_hit: bool,
        url: str | None = None,
    ) -> AudioAsset:
        return AudioAsset(
            asset_id=key,
            asset_type=AudioAssetType.NARRATION,
            provider=self.provider_name,
            playback_url=url or self.storage.url_for(key),
            duration=duration,
            metadata={
                "cache_key": key,
                "model": self.model,
                "voice_id": self.voice_id,
                "usage_characters": billed,
                "cache_hit": cache_hit,
            },
        )

    def _record(
        self,
        started: float,
        spoken: str,
        rate: int,
        outcome: str,
        *,
        cache_hit: bool,
        billed: int | None = None,
        stage: str = "cache",
        audio_seconds: float | None = None,
    ) -> None:
        """The one final event of this attempt.  Counts and outcomes only: no text, no URLs."""

        metadata: dict[str, Any] = {
            "outcome": outcome,
            "model": self.model,
            "protocol": self.protocol_version,
            "voice_id": self.voice_id,
            "speech_rate": rate,
            "cache_hit": cache_hit,
            # A local count of what was sent - not what was billed.
            "sent_characters": len(spoken),
        }
        if cache_hit:
            # Nothing was sent to the service, so nothing was spent: a known zero.
            metadata.update(
                {"estimated_cost_cny": 0.0, "estimated_cost_cny_low": 0.0,
                 "estimated_cost_cny_high": 0.0, "cost_basis": "cache_hit", "price_version": PRICE_VERSION}
            )
        else:
            metadata["billed_characters"] = billed
            metadata.update(price_for(billed))
            if outcome != "ok":
                metadata["failed_stage"] = stage
        if audio_seconds is not None:
            metadata["audio_seconds"] = round(audio_seconds, 3)
        self.ledger.record(
            UsageEvent(
                provider=self.provider_name,
                operation="tts",
                elapsed_ms=int((perf_counter() - started) * 1000),
                usage_characters=billed,
                metadata=metadata,
            )
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()


def _spoken(text: str) -> str:
    """The text as spoken: MiniMax's cue markers (``(breath)``) are not read out by this voice."""

    for tag in CUE_TAGS.values():
        text = text.replace(tag, " ")
    return " ".join(text.split())


def _stored_duration(metadata: dict[str, Any]) -> int | None:
    value = metadata.get("duration_seconds")
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _is_count(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value) and value >= 0 and float(value).is_integer()


def _parse_stream(content: bytes) -> tuple[bytes, int | None]:
    """The PCM and the billed characters of one reply, or an error if it did not complete."""

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ProviderInvalidResponseError("doubao tts returned an unreadable reply") from error
    decoder = json.JSONDecoder()
    pcm = bytearray()
    billed: int | None = None
    finished = False
    cursor = 0
    while True:
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
        if cursor >= len(text):
            break
        try:
            item, cursor = decoder.raw_decode(text, cursor)
        except ValueError as error:
            raise ProviderInvalidResponseError("doubao tts returned malformed JSON") from error
        if not isinstance(item, dict):
            raise ProviderInvalidResponseError("doubao tts returned a non-object chunk")
        usage = item.get("usage")
        if isinstance(usage, dict) and _is_count(usage.get("text_words")):
            billed = int(usage["text_words"])  # a reported 0 stays 0
        code = item.get("code")
        if isinstance(code, bool) or not isinstance(code, int):
            raise ProviderInvalidResponseError("doubao tts returned a chunk without a code")
        if code == 0:
            data = item.get("data")
            if isinstance(data, str) and data:
                try:
                    pcm.extend(base64.b64decode(data, validate=True))
                except (binascii.Error, ValueError) as error:
                    raise ProviderInvalidResponseError("doubao tts returned invalid audio") from error
        elif code == END_CODE:
            finished = True
        else:
            raise ProviderInvalidResponseError(f"doubao tts failed with code {code}")
    if not finished:
        raise ProviderIncompleteResponseError("doubao tts reply ended without the completion code")
    return bytes(pcm), billed


def _validated_seconds(pcm: bytes) -> float:
    if not pcm or len(pcm) % 2:
        raise ProviderInvalidResponseError("doubao tts returned no usable audio")
    seconds = len(pcm) / BYTES_PER_SECOND
    if seconds > MAX_AUDIO_SECONDS:
        raise ProviderInvalidResponseError("doubao tts returned implausibly long audio")
    return seconds


def _wav(pcm: bytes) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        output.writeframes(pcm)
    return buffer.getvalue()
