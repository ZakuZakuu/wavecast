"""Async narration materialization outside deterministic episode lifecycle code."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from typing import Any

from pydantic import ValidationError

from wavecast.models.dialogue import VoiceRoleSnapshot
from wavecast.models.episode import NarrationSegment, SegmentKind, SegmentState
from wavecast.narration import render_narration
from wavecast.providers.contracts import (
    AudioAsset,
    AudioAssetType,
    ObjectStorageProvider,
    TTSProvider,
)
from wavecast.providers.dialogue_speech import DialogueSpeechProvider
from wavecast.providers.errors import (
    ProviderConfigurationError,
    ProviderError,
    ProviderInvalidResponseError,
)
from wavecast.providers.speech import SpeechRequest
from wavecast.speech import SpeechDirector, SpeechProfile
from wavecast.spoken_form import has_unspeakable_script

logger = logging.getLogger(__name__)


class NarrationMaterializer:
    """Turn script-ready narration into a stored, browser-playable asset."""

    def __init__(
        self,
        tts_provider: TTSProvider,
        storage: ObjectStorageProvider,
        *,
        dialogue_speech: DialogueSpeechProvider | None = None,
        dialogue_voices: Sequence[VoiceRoleSnapshot] = (),
        dialogue_speed: float | None = None,
    ) -> None:
        self.tts_provider = tts_provider
        self.storage = storage
        # Two-host passages are voiced by their own provider with a fixed voice-per-host
        # mapping; without them a dialogue segment cannot be materialized (it is not read out
        # by the one-voice TTS).
        self.dialogue_speech = dialogue_speech
        self.dialogue_voices = tuple(dialogue_voices)
        self.dialogue_speed = dialogue_speed
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
        if segment.dialogue is not None:
            return await self._materialize_dialogue(segment)
        synthesis_text = segment.tts_text or segment.narration_text
        if not synthesis_text:
            raise ProviderInvalidResponseError("narration segment has no script text")
        if has_unspeakable_script(synthesis_text):
            # Last line of defence: never send text the voice cannot read to the TTS provider.
            logger.warning("narration_skipped segment_id=%s reason=unspeakable_script", segment.id)
            segment.state = SegmentState.SKIPPED
            return segment

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

    async def _materialize_dialogue(self, segment: NarrationSegment) -> NarrationSegment:
        block = segment.dialogue
        assert block is not None
        provider = self.dialogue_speech
        if provider is None or not self.dialogue_voices:
            raise ProviderConfigurationError("no dialogue voices are configured")
        if any(has_unspeakable_script(turn.tts_text or turn.text) for turn in block.turns):
            logger.warning("narration_skipped segment_id=%s reason=unspeakable_script", segment.id)
            segment.state = SegmentState.SKIPPED
            return segment
        try:
            request = SpeechRequest.dialogue(
                block, list(self.dialogue_voices), speed=self.dialogue_speed
            )
        except ValidationError as error:
            raise ProviderConfigurationError("dialogue voices do not cover the speakers") from error
        cache_key = provider.cache_key(request)
        lock = self._locks.setdefault(cache_key, asyncio.Lock())
        async with lock:
            cached = await self.storage.get(cache_key)
            cached_duration = _stored_duration(cached.metadata) if cached else None
            if cached is not None and cached_duration is not None:
                # Restored or repeated: the audio already exists, so nothing is synthesized.
                self._apply_dialogue_asset(
                    segment,
                    AudioAsset(
                        asset_id=cache_key,
                        asset_type=AudioAssetType.NARRATION,
                        provider=provider.provider_name,
                        playback_url=self.storage.url_for(cache_key),
                        duration=cached_duration,
                        metadata={"cache_key": cache_key, "cache_hit": True},
                    ),
                    request,
                )
                return segment

            segment.state = SegmentState.AUDIO_GENERATING
            try:
                asset = await provider.synthesize_dialogue(request)
                if asset.asset_type is not AudioAssetType.NARRATION:
                    raise ProviderInvalidResponseError("dialogue speech returned a non-narration asset")
                if not asset.playback_url or asset.duration <= 0:
                    raise ProviderInvalidResponseError("dialogue speech returned an invalid audio asset")
            except asyncio.CancelledError:
                # Cancelled or superseded mid-synthesis: back to a clean, unpublished state.
                segment.state = SegmentState.SCRIPT_READY
                raise
            except ProviderError:
                segment.state = SegmentState.SCRIPT_READY
                raise
            except Exception as error:
                segment.state = SegmentState.SCRIPT_READY
                raise ProviderInvalidResponseError("dialogue materialization failed") from error
            self._apply_dialogue_asset(segment, asset, request)
            return segment

    def _apply_dialogue_asset(
        self, segment: NarrationSegment, asset: AudioAsset, request: SpeechRequest
    ) -> None:
        # The actual audio length (not the estimate) is what the timeline plans with.
        self._apply_asset(segment, asset)
        segment.dialogue_voices = list(request.roles)

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
