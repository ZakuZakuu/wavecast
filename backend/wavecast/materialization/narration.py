"""Async narration materialization outside deterministic episode lifecycle code."""

from __future__ import annotations

import asyncio
from typing import Any

from wavecast.models.episode import NarrationSegment, SegmentKind, SegmentState
from wavecast.narration import render_narration
from wavecast.providers.contracts import (
    AudioAsset,
    AudioAssetType,
    ObjectStorageProvider,
    TTSProvider,
)
from wavecast.providers.errors import ProviderError, ProviderInvalidResponseError
from wavecast.speech import SpeechDirector, SpeechProfile


class NarrationMaterializer:
    """Turn script-ready narration into a stored, browser-playable asset."""

    def __init__(
        self,
        tts_provider: TTSProvider,
        storage: ObjectStorageProvider,
    ) -> None:
        self.tts_provider = tts_provider
        self.storage = storage
        self._locks: dict[str, asyncio.Lock] = {}

    async def materialize(self, segment: NarrationSegment) -> NarrationSegment:
        if segment.kind is not SegmentKind.NARRATION:
            raise ProviderInvalidResponseError(
                "narration materializer received a non-narration segment"
            )
        if segment.state is SegmentState.AUDIO_READY:
            return segment
        if segment.state is not SegmentState.SCRIPT_READY:
            raise ProviderInvalidResponseError(
                f"narration materialization requires SCRIPT_READY, got {segment.state.value}"
            )
        synthesis_text = segment.tts_text or segment.narration_text
        if not synthesis_text:
            raise ProviderInvalidResponseError("narration segment has no script text")

        rendered = render_narration(synthesis_text, segment.tts_cues)
        # Profile selection must inspect authored synthesis text, not rendered cue markers.
        # Cue markers are transport instructions rather than spoken language.
        baseline_speed = getattr(
            self.tts_provider,
            "speech_speed_baseline",
            SpeechDirector.DEFAULT_BASE_SPEED,
        )
        profile = SpeechDirector.profile_for(
            segment.narration_role,
            synthesis_text,
            baseline_speed=baseline_speed if isinstance(baseline_speed, (int, float)) else None,
        )
        cache_key = _provider_cache_key(
            self.tts_provider, rendered.text, rendered.recognized_cues, profile
        )
        lock = self._locks.setdefault(cache_key or segment.id, asyncio.Lock())
        async with lock:
            if cache_key:
                cached = await self.storage.get(cache_key)
                cached_duration = _stored_duration(cached.metadata) if cached else None
                if cached is not None and cached_duration is not None:
                    self._apply_asset(
                        segment,
                        AudioAsset(
                            asset_id=cache_key,
                            asset_type=AudioAssetType.NARRATION,
                            provider=getattr(self.tts_provider, "provider_name", "tts"),
                            playback_url=self.storage.url_for(cache_key),
                            duration=cached_duration,
                            metadata={
                                "cache_key": cache_key,
                                "cache_hit": True,
                                **_profile_metadata(profile, segment),
                            },
                        ),
                    )
                    return segment

            segment.state = SegmentState.AUDIO_GENERATING
            try:
                asset = await self.tts_provider.synthesize(
                    rendered.text, cues=list(rendered.recognized_cues), profile=profile
                )
                if asset.asset_type is not AudioAssetType.NARRATION:
                    raise ProviderInvalidResponseError(
                        "TTS provider returned a non-narration asset"
                    )
                if not asset.playback_url or asset.duration <= 0:
                    raise ProviderInvalidResponseError(
                        "TTS provider returned an invalid audio asset"
                    )
                asset.metadata = {**asset.metadata, **_profile_metadata(profile, segment)}
                self._apply_asset(segment, asset)
                return segment
            except ProviderError:
                segment.state = SegmentState.SCRIPT_READY
                raise
            except Exception as error:
                segment.state = SegmentState.SCRIPT_READY
                raise ProviderInvalidResponseError("narration materialization failed") from error

    @staticmethod
    def _apply_asset(segment: NarrationSegment, asset: AudioAsset) -> None:
        segment.asset_ref = asset.asset_id
        segment.audio_source_url = asset.playback_url
        segment.actual_duration_seconds = asset.duration
        segment.state = SegmentState.AUDIO_READY


def _provider_cache_key(
    provider: TTSProvider,
    rendered_text: str,
    cues: tuple[str, ...],
    profile: SpeechProfile,
) -> str | None:
    cache_key = getattr(provider, "cache_key", None)
    if not callable(cache_key):
        return None
    value = cache_key(rendered_text, cues, profile=profile)
    return value if isinstance(value, str) and value else None


def _profile_metadata(profile: SpeechProfile, segment: NarrationSegment) -> dict[str, Any]:
    return {
        "speech_profile_id": profile.profile_id,
        "speech_profile_version": profile.version,
        "speed": profile.speed,
        "language_boost": profile.language_boost,
        "narration_role": segment.narration_role.value,
    }


def _stored_duration(metadata: dict[str, Any]) -> int | None:
    value = metadata.get("duration_seconds")
    return value if isinstance(value, int) and value > 0 else None
