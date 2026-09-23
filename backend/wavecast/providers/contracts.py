from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol

from pydantic import BaseModel, Field

from .profiles import InferenceProfile, StructuredTransport

if TYPE_CHECKING:
    from wavecast.intelligence.models import ResolvedTrack
    from wavecast.speech import SpeechProfile


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str
    provider: str
    query: str
    score: float | None = None
    content: str | None = None
    published_at: str | None = None
    request_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TrackMetadata(BaseModel):
    track_ref: str
    title: str
    artist: str
    duration_seconds: int
    playable: bool
    metadata: dict[str, Any] = Field(default_factory=dict)


class AudioAssetType(StrEnum):
    MUSIC = "MUSIC"
    NARRATION = "NARRATION"


class AudioAsset(BaseModel):
    """Provider-neutral playback asset shared by music and narration adapters."""

    asset_id: str = Field(min_length=1)
    asset_type: AudioAssetType
    provider: str = Field(min_length=1)
    playback_url: str = Field(min_length=1)
    duration: int = Field(gt=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def asset_ref(self) -> str:
        """Compatibility alias for the pre-Phase-4.2 TTS contract."""
        return self.asset_id

    @property
    def duration_seconds(self) -> int:
        """Compatibility alias for runtime segment duration handling."""
        return self.duration


class AudioSource(BaseModel):
    """A browser-loadable audio URL and its deterministic duration metadata."""

    source_url: str = Field(min_length=1)
    duration_seconds: int = Field(gt=0)


class AudioProvider(Protocol):
    """Resolves already-selected segments to browser audio sources."""

    def music_source(self, track_ref: str) -> AudioSource: ...

    def narration_source(
        self, segment_id: str, narration_text: str, duration_seconds: int
    ) -> AudioSource: ...


class LLMProvider(Protocol):
    async def structured(self, prompt: str, output_type: type[BaseModel]) -> BaseModel: ...


class ProgressiveLLMProvider(Protocol):
    async def structured(
        self,
        prompt: str,
        output_type: type[BaseModel],
        *,
        transport: StructuredTransport,
        profile: InferenceProfile,
        stage: str | None = None,
    ) -> BaseModel: ...


class SearchProvider(Protocol):
    async def search(
        self, query: str, *, limit: int = 5, stage: str | None = None
    ) -> list[SearchResult]: ...


class TTSProvider(Protocol):
    async def synthesize(
        self, text: str, *, cues: list[str], profile: SpeechProfile | None = None
    ) -> AudioAsset: ...


class MusicProvider(Protocol):
    """Catalog and playback boundary consumed by deterministic composition code.

    Proposal matching intentionally lives in ``intelligence.resolution``.  A
    provider only exposes catalog primitives and receives a resolved identity
    when composition asks for a playable asset.
    """

    async def search(self, query: str, *, limit: int = 5) -> list[TrackMetadata]: ...

    async def resolve_track(self, track_ref: str) -> TrackMetadata: ...

    async def get_playback_asset(self, resolved_track: ResolvedTrack) -> AudioAsset: ...


class AudioAnalysisProvider(Protocol):
    async def analyze(self, track_ref: str) -> dict[str, float]: ...


class ObjectStorageProvider(Protocol):
    async def put(
        self,
        key: str,
        content: bytes,
        content_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> str: ...

    async def get(self, key: str) -> Any | None: ...

    def url_for(self, key: str) -> str: ...


class CoverRenderer(Protocol):
    def render_svg(self, *, title: str, seed: int, palette: tuple[str, str]) -> str: ...
