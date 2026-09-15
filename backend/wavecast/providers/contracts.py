from typing import Any, Protocol

from pydantic import BaseModel, Field


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


class AudioAsset(BaseModel):
    asset_ref: str
    duration_seconds: int


class LLMProvider(Protocol):
    async def structured(self, prompt: str, output_type: type[BaseModel]) -> BaseModel: ...


class SearchProvider(Protocol):
    async def search(self, query: str, *, limit: int = 5) -> list[SearchResult]: ...


class TTSProvider(Protocol):
    async def synthesize(self, text: str, *, cues: list[str]) -> AudioAsset: ...


class MusicProvider(Protocol):
    async def search(self, query: str) -> list[TrackMetadata]: ...

    async def resolve_track(self, track_ref: str) -> TrackMetadata: ...

    async def get_stream_source(self, track_ref: str) -> str: ...


class AudioAnalysisProvider(Protocol):
    async def analyze(self, track_ref: str) -> dict[str, float]: ...


class ObjectStorageProvider(Protocol):
    async def put(self, key: str, content: bytes, content_type: str) -> str: ...


class CoverRenderer(Protocol):
    def render_svg(self, *, title: str, seed: int, palette: tuple[str, str]) -> str: ...
