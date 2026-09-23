"""MiniMax Speech 2.8 HD synchronous TTS adapter."""

from __future__ import annotations

import asyncio
import math
from time import perf_counter
from typing import Any

import httpx

from wavecast.narration import CUE_RENDERING_VERSION
from wavecast.speech import SpeechProfile

from .config import ProviderSettings
from .contracts import AudioAsset, AudioAssetType, ObjectStorageProvider
from .errors import ProviderConfigurationError, ProviderError, ProviderInvalidResponseError
from .http import request_json
from .tts_cache import build_tts_cache_key
from .usage import UsageEvent, UsageLedger


class MiniMaxTTSProvider:
    """Persist MiniMax hex audio before exposing it as a WaveCast URL."""

    provider_name = "minimax"
    endpoint_path = "/v1/t2a_v2"
    audio_settings = {
        "sample_rate": 32000,
        "bitrate": 128000,
        "format": "mp3",
        "channel": 1,
    }

    def __init__(
        self,
        settings: ProviderSettings | None = None,
        *,
        storage: ObjectStorageProvider | None = None,
        ledger: UsageLedger | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or ProviderSettings.from_env()
        if storage is None:
            from wavecast.storage.assets import LocalObjectStorageProvider

            storage = LocalObjectStorageProvider()
        self.storage = storage
        self.ledger = ledger or UsageLedger()
        self.client = client or httpx.AsyncClient(timeout=self.settings.timeout_seconds)
        self._owns_client = client is None
        self._locks: dict[str, asyncio.Lock] = {}

    def cache_key(
        self,
        rendered_text: str,
        cues: list[str] | tuple[str, ...],
        *,
        profile: SpeechProfile | None = None,
    ) -> str:
        speed = profile.speed if profile is not None else self.settings.minimax_tts_speed
        language_boost = (
            profile.language_boost
            if profile is not None and profile.language_boost is not None
            else self.settings.minimax_tts_language_boost
        )
        return build_tts_cache_key(
            provider=self.provider_name,
            model=self.settings.minimax_tts_model,
            voice_id=self.settings.minimax_tts_voice_id or "",
            speed=speed,
            language_boost=language_boost,
            audio_settings=self.audio_settings,
            rendered_text=rendered_text,
            recognized_cues=cues,
            rendering_version=CUE_RENDERING_VERSION,
        )

    async def synthesize(
        self, text: str, *, cues: list[str], profile: SpeechProfile | None = None
    ) -> AudioAsset:
        started_at = perf_counter()
        cache_key = self.cache_key(text, cues, profile=profile)
        lock = self._locks.setdefault(cache_key, asyncio.Lock())
        async with lock:
            try:
                api_key, voice_id = self._credentials()
                cached = await self.storage.get(cache_key)
                if cached is not None:
                    duration = _stored_duration(cached.metadata)
                    if duration is not None:
                        self._record_usage(
                            started_at,
                            len(text),
                            success=True,
                            cache_hit=True,
                            metadata={"cache_key": cache_key, "duration_seconds": duration},
                        )
                        return self._asset(cache_key, duration, cached.metadata, cache_hit=True)

                payload, _response = await request_json(
                    self.client,
                    provider=self.provider_name,
                    method="POST",
                    url=f"{self.settings.minimax_tts_base_url.rstrip('/')}{self.endpoint_path}",
                    max_attempts=1,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=self._request_payload(text, voice_id, profile),
                )
                audio_bytes, extra_info = _decode_response(payload)
                duration = _duration_seconds(audio_bytes, extra_info)
                usage_characters = _usage_characters(extra_info, text)
                url = await self.storage.put(
                    cache_key,
                    audio_bytes,
                    "audio/mpeg",
                    metadata={
                        "duration_seconds": duration,
                        "duration_source": "extra_info.audio_length"
                        if "audio_length" in extra_info
                        else "mp3_frame_header",
                        "provider": self.provider_name,
                        "model": self.settings.minimax_tts_model,
                        "voice_id": voice_id,
                        "usage_characters": usage_characters,
                    },
                )
                self._record_usage(
                    started_at,
                    usage_characters,
                    success=True,
                    cache_hit=False,
                    metadata={"cache_key": cache_key, "duration_seconds": duration},
                )
                return AudioAsset(
                    asset_id=cache_key,
                    asset_type=AudioAssetType.NARRATION,
                    provider=self.provider_name,
                    playback_url=url,
                    duration=duration,
                    metadata={
                        "cache_key": cache_key,
                        "model": self.settings.minimax_tts_model,
                        "voice_id": voice_id,
                        "usage_characters": usage_characters,
                    },
                )
            except ProviderError:
                self._record_usage(
                    started_at,
                    len(text),
                    success=False,
                    cache_hit=False,
                    metadata={"cache_key": cache_key},
                )
                raise
            except Exception as error:
                self._record_usage(
                    started_at,
                    len(text),
                    success=False,
                    cache_hit=False,
                    metadata={"cache_key": cache_key},
                )
                raise ProviderInvalidResponseError(
                    "minimax returned an invalid TTS response"
                ) from error

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    def _credentials(self) -> tuple[str, str]:
        if self.settings.mode != "live" or not self.settings.minimax_api_key:
            raise ProviderConfigurationError(
                "minimax live adapter requires MINIMAX_API_KEY and live mode"
            )
        if not self.settings.minimax_tts_voice_id:
            raise ProviderConfigurationError("minimax TTS requires MINIMAX_TTS_VOICE_ID")
        return self.settings.minimax_api_key, self.settings.minimax_tts_voice_id

    def _request_payload(
        self, text: str, voice_id: str, profile: SpeechProfile | None = None
    ) -> dict[str, Any]:
        speed = profile.speed if profile is not None else self.settings.minimax_tts_speed
        language_boost = (
            profile.language_boost
            if profile is not None and profile.language_boost is not None
            else self.settings.minimax_tts_language_boost
        )
        return {
            "model": self.settings.minimax_tts_model,
            "text": text,
            "stream": False,
            "language_boost": language_boost,
            "output_format": "hex",
            "voice_setting": {
                "voice_id": voice_id,
                "speed": speed,
                "vol": 1,
                "pitch": 0,
            },
            "audio_setting": dict(self.audio_settings),
        }

    def _asset(
        self, cache_key: str, duration: int, metadata: dict[str, Any], *, cache_hit: bool
    ) -> AudioAsset:
        return AudioAsset(
            asset_id=cache_key,
            asset_type=AudioAssetType.NARRATION,
            provider=self.provider_name,
            playback_url=self.storage.url_for(cache_key),
            duration=duration,
            metadata={
                "cache_key": cache_key,
                "model": self.settings.minimax_tts_model,
                "voice_id": self.settings.minimax_tts_voice_id,
                "usage_characters": metadata.get("usage_characters"),
                "cache_hit": cache_hit,
            },
        )

    def _record_usage(
        self,
        started_at: float,
        usage_characters: int,
        *,
        success: bool,
        cache_hit: bool,
        metadata: dict[str, Any],
    ) -> None:
        self.ledger.record(
            UsageEvent(
                provider=self.provider_name,
                operation="tts",
                elapsed_ms=int((perf_counter() - started_at) * 1000),
                usage_characters=usage_characters,
                metadata={
                    "model": self.settings.minimax_tts_model,
                    "success": success,
                    "cache_hit": cache_hit,
                    **metadata,
                },
            )
        )


def _decode_response(payload: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    base_resp = payload.get("base_resp")
    if not isinstance(base_resp, dict):
        raise ProviderInvalidResponseError("minimax response omitted base_resp")
    status_code = base_resp.get("status_code")
    if not isinstance(status_code, int):
        raise ProviderInvalidResponseError("minimax response had an invalid status code")
    if status_code != 0:
        raise ProviderInvalidResponseError(f"minimax synthesis failed with status {status_code}")

    data = payload.get("data")
    if not isinstance(data, dict):
        raise ProviderInvalidResponseError("minimax response omitted audio data")
    audio_hex = data.get("audio")
    if not isinstance(audio_hex, str) or not audio_hex.strip():
        raise ProviderInvalidResponseError("minimax response omitted audio bytes")
    try:
        audio_bytes = bytes.fromhex(audio_hex)
    except ValueError as error:
        raise ProviderInvalidResponseError(
            "minimax response contained invalid audio hex"
        ) from error
    if not audio_bytes:
        raise ProviderInvalidResponseError("minimax response contained empty audio bytes")

    if "extra_info" not in payload:
        extra_info: dict[str, Any] = {}
    elif isinstance(payload["extra_info"], dict):
        extra_info = payload["extra_info"]
    else:
        raise ProviderInvalidResponseError("minimax response contained malformed extra_info")
    audio_format = extra_info.get("audio_format")
    if audio_format is not None and audio_format != "mp3":
        raise ProviderInvalidResponseError("minimax response was not an mp3 asset")
    audio_length = extra_info.get("audio_length")
    if audio_length is not None and (
        isinstance(audio_length, bool)
        or not isinstance(audio_length, (int, float))
        or not math.isfinite(float(audio_length))
        or audio_length <= 0
    ):
        raise ProviderInvalidResponseError("minimax response contained invalid audio_length")
    return audio_bytes, extra_info


def _duration_seconds(audio_bytes: bytes, extra_info: dict[str, Any]) -> int:
    audio_length = extra_info.get("audio_length")
    if isinstance(audio_length, (int, float)) and not isinstance(audio_length, bool):
        return _nearest_second(float(audio_length) / 1000)
    duration = _mp3_duration_seconds(audio_bytes)
    if duration is None:
        raise ProviderInvalidResponseError("minimax audio duration could not be determined")
    return _nearest_second(duration)


def _mp3_duration_seconds(audio_bytes: bytes) -> float | None:
    bitrate_table = {
        3: (None, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, None),
        2: (None, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, None),
    }
    sample_rates = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}
    total_seconds = 0.0
    offset = 0
    frames = 0
    while offset + 4 <= len(audio_bytes):
        header = int.from_bytes(audio_bytes[offset : offset + 4], "big")
        if (header >> 21) & 0x7FF != 0x7FF:
            offset += 1
            continue
        version = (header >> 19) & 0b11
        layer = (header >> 17) & 0b11
        bitrate_index = (header >> 12) & 0xF
        sample_index = (header >> 10) & 0x3
        padding = (header >> 9) & 0x1
        mpeg_version = {3: 3, 2: 2, 0: 0}.get(version)
        if mpeg_version is None or layer != 1 or bitrate_index == 15 or sample_index == 3:
            offset += 1
            continue
        bitrate_values = bitrate_table[3 if mpeg_version == 3 else 2]
        bitrate = bitrate_values[bitrate_index]
        sample_rate = sample_rates[mpeg_version][sample_index]
        if bitrate is None:
            offset += 1
            continue
        frame_length = (
            (144 if mpeg_version == 3 else 72) * bitrate * 1000 // sample_rate
        ) + padding
        if frame_length <= 4 or offset + frame_length > len(audio_bytes):
            offset += 1
            continue
        samples = 1152 if mpeg_version == 3 else 576
        total_seconds += samples / sample_rate
        frames += 1
        offset += frame_length
    return total_seconds if frames else None


def _nearest_second(seconds: float) -> int:
    """Map positive audio duration to the integer timeline using half-up rounding."""
    return max(1, math.floor(seconds + 0.5))


def _stored_duration(metadata: dict[str, Any]) -> int | None:
    value = metadata.get("duration_seconds")
    if isinstance(value, int) and value > 0:
        return value
    return None


def _usage_characters(extra_info: dict[str, Any], text: str) -> int:
    value = extra_info.get("usage_characters")
    if isinstance(value, int) and value >= 0:
        return value
    return len(text)
