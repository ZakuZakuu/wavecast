from __future__ import annotations

import asyncio
import math
from hashlib import sha1
from io import BytesIO
from typing import TYPE_CHECKING
from urllib.parse import quote
from wave import open as open_wave

from pydantic import BaseModel

from wavecast.narration import CUE_RENDERING_VERSION
from wavecast.speech import SpeechProfile

from .contracts import (
    AudioAsset,
    AudioAssetType,
    AudioSource,
    ObjectStorageProvider,
    SearchResult,
    TrackMetadata,
)
from .tts_cache import build_tts_cache_key

if TYPE_CHECKING:
    from wavecast.intelligence.models import ResolvedTrack


class FakeSearchProvider:
    async def search(
        self, query: str, *, limit: int = 5, stage: str | None = None
    ) -> list[SearchResult]:
        del stage
        return [
            SearchResult(
                title=f"Mock research for {query}",
                url="https://example.invalid/mock-research",
                snippet="Deterministic fixture result; no network request was made.",
                provider="fake-search",
                query=query,
                score=1.0,
            )
        ][:limit]


class FakeLLMProvider:
    async def structured(self, prompt: str, output_type: type[BaseModel]) -> BaseModel:
        raise NotImplementedError(
            "FakeLLMProvider requires an explicit fixture response per agent contract"
        )


class FakeTTSProvider:
    async def synthesize(
        self, text: str, *, cues: list[str], profile: SpeechProfile | None = None
    ) -> AudioAsset:
        digest = sha1(
            f"{text}|{cues}|{profile.model_dump_json() if profile else ''}".encode()
        ).hexdigest()[:12]
        playback_url = f"fake-tts://{digest}"
        return AudioAsset(
            asset_id=playback_url,
            asset_type=AudioAssetType.NARRATION,
            provider="fake-tts",
            playback_url=playback_url,
            duration=max(8, len(text) // 6),
            metadata={"cues": list(cues)},
        )


class MockTTSProvider:
    """Credential-free TTS with the same storage-backed materialization path."""

    provider_name = "mock-tts"
    model = "mock-speech"
    voice_id = "mock-narrator"
    speed = 0.8
    speech_speed_baseline = 0.8
    language_boost = "auto"
    audio_settings = {"sample_rate": 8000, "bitrate": 128000, "format": "wav", "channel": 1}

    def __init__(self, storage: ObjectStorageProvider | None = None) -> None:
        if storage is None:
            from wavecast.storage.assets import LocalObjectStorageProvider

            storage = LocalObjectStorageProvider()
        self.storage = storage
        self._locks: dict[str, asyncio.Lock] = {}
        self.calls = 0

    def cache_key(
        self,
        rendered_text: str,
        cues: list[str] | tuple[str, ...],
        *,
        profile: SpeechProfile | None = None,
    ) -> str:
        speed = profile.speed if profile is not None else self.speed
        language_boost = (
            profile.language_boost
            if profile is not None and profile.language_boost is not None
            else self.language_boost
        )
        return build_tts_cache_key(
            provider=self.provider_name,
            model=self.model,
            voice_id=self.voice_id,
            speed=speed,
            language_boost=language_boost,
            audio_settings=self.audio_settings,
            rendered_text=rendered_text,
            recognized_cues=cues,
            rendering_version=CUE_RENDERING_VERSION,
            extension="wav",
        )

    async def synthesize(
        self, text: str, *, cues: list[str], profile: SpeechProfile | None = None
    ) -> AudioAsset:
        cache_key = self.cache_key(text, cues, profile=profile)
        lock = self._locks.setdefault(cache_key, asyncio.Lock())
        async with lock:
            cached = await self.storage.get(cache_key)
            if cached is not None:
                return self._asset(cache_key, cached.metadata.get("duration_seconds", 1), True)
            self.calls += 1
            speed = profile.speed if profile is not None else self.speed
            duration = max(1, min(300, math.ceil(len(text) / (12 * speed))))
            content = _mock_narration_wav(duration)
            url = await self.storage.put(
                cache_key,
                content,
                "audio/wav",
                metadata={"duration_seconds": duration, "provider": self.provider_name},
            )
            return AudioAsset(
                asset_id=cache_key,
                asset_type=AudioAssetType.NARRATION,
                provider=self.provider_name,
                playback_url=url,
                duration=duration,
                metadata={"cache_key": cache_key, "cache_hit": False},
            )

    def _asset(self, cache_key: str, duration: object, cache_hit: bool) -> AudioAsset:
        seconds = duration if isinstance(duration, int) and duration > 0 else 1
        return AudioAsset(
            asset_id=cache_key,
            asset_type=AudioAssetType.NARRATION,
            provider=self.provider_name,
            playback_url=self.storage.url_for(cache_key),
            duration=seconds,
            metadata={"cache_key": cache_key, "cache_hit": cache_hit},
        )


def _mock_narration_wav(duration_seconds: int) -> bytes:
    buffer = BytesIO()
    with open_wave(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(1)
        wav.setframerate(8000)
        wav.writeframes(b"\x80" * (8000 * duration_seconds))
    return buffer.getvalue()


class MockAudioProvider:
    """Deterministic local audio-source provider; no network or paid API calls."""

    _music_durations = {
        "mock:opening": 22,
        "mock:bridge": 24,
        "mock:resolution": 26,
        "mock:finale": 25,
    }

    def __init__(self, base_url: str = "/api/audio/mock") -> None:
        self.base_url = base_url.rstrip("/")

    def music_source(self, track_ref: str) -> AudioSource:
        duration = self._music_durations.get(track_ref, 30)
        encoded_ref = quote(track_ref, safe="")
        return AudioSource(
            source_url=f"{self.base_url}/music/{encoded_ref}?duration={duration}",
            duration_seconds=duration,
        )

    def narration_source(
        self, segment_id: str, narration_text: str, duration_seconds: int
    ) -> AudioSource:
        del narration_text
        encoded_id = quote(segment_id, safe="")
        return AudioSource(
            source_url=f"{self.base_url}/narration/{encoded_id}?duration={duration_seconds}",
            duration_seconds=duration_seconds,
        )


class FakeMusicProvider:
    def __init__(self) -> None:
        self._tracks = {
            "mock:opening": TrackMetadata(
                track_ref="mock:opening",
                title="Neon First Light",
                artist="Mira Fields",
                duration_seconds=22,
                playable=True,
            ),
            "mock:bridge": TrackMetadata(
                track_ref="mock:bridge",
                title="Midnight Transfer",
                artist="Signal Garden",
                duration_seconds=24,
                playable=True,
            ),
            "mock:resolution": TrackMetadata(
                track_ref="mock:resolution",
                title="Daybreak in Stereo",
                artist="Southbound FM",
                duration_seconds=26,
                playable=True,
            ),
            "mock:finale": TrackMetadata(
                track_ref="mock:finale",
                title="Afterimage Avenue",
                artist="Southbound FM",
                duration_seconds=25,
                playable=True,
            ),
        }

    async def search(self, query: str, *, limit: int = 5) -> list[TrackMetadata]:
        terms = [term for term in query.casefold().split() if term]
        return [
            track
            for track in self._tracks.values()
            if all(term in f"{track.title} {track.artist}".casefold() for term in terms)
        ][:limit]

    async def resolve_track(self, track_ref: str) -> TrackMetadata:
        return self._tracks[track_ref]

    async def get_playback_asset(self, resolved_track: ResolvedTrack) -> AudioAsset:
        track_ref = resolved_track.track_ref
        metadata = await self.resolve_track(track_ref)
        return AudioAsset(
            asset_id=metadata.track_ref,
            asset_type=AudioAssetType.MUSIC,
            provider="fake-music",
            playback_url=f"fake-music://{track_ref}",
            duration=metadata.duration_seconds,
            metadata=metadata.model_dump(),
        )


class MockMusicProvider(FakeMusicProvider):
    """Credential-free music catalog whose assets are loadable by the local API."""

    def __init__(self, base_url: str = "/api/audio/mock") -> None:
        super().__init__()
        self.base_url = base_url.rstrip("/")

    async def get_playback_asset(self, resolved_track: ResolvedTrack) -> AudioAsset:
        metadata = await self.resolve_track(resolved_track.track_ref)
        playback_url = f"{self.base_url}/music/{quote(metadata.track_ref, safe='')}?duration={metadata.duration_seconds}"
        return AudioAsset(
            asset_id=metadata.track_ref,
            asset_type=AudioAssetType.MUSIC,
            provider="mock-music",
            playback_url=playback_url,
            duration=metadata.duration_seconds,
            metadata=metadata.model_dump(),
        )


class FakeCoverRenderer:
    def render_svg(self, *, title: str, seed: int, palette: tuple[str, str]) -> str:
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400">'
            f'<rect width="400" height="400" fill="{palette[0]}"/>'
            f'<circle cx="{seed % 400}" cy="180" r="130" fill="{palette[1]}"/>'
            f'<text x="24" y="340" fill="white" font-size="24">{title}</text></svg>'
        )
