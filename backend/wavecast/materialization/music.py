from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol

import httpx

if TYPE_CHECKING:
    from wavecast.providers.playback import ResolvedPlaybackRequest
from urllib.parse import unquote, urlsplit

from pydantic import BaseModel, ConfigDict, Field


class MusicSourceKind(StrEnum):
    OWNED_ASSET = "OWNED_ASSET"
    SIDECAR_PROXY = "SIDECAR_PROXY"
    AUDIUS_PROXY = "AUDIUS_PROXY"
    UNSUPPORTED = "UNSUPPORTED"


class MusicSourceClassification(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: MusicSourceKind
    source_url: str
    identity: str
    provider: str | None = None
    reason_code: str | None = None


class SnapshotBytes(BaseModel):
    model_config = ConfigDict(frozen=True)

    content: bytes = Field(min_length=1)
    content_type: str = Field(min_length=1)
    duration_seconds: int = Field(gt=0)


class StoredMusicAsset(BaseModel):
    model_config = ConfigDict(frozen=True)

    asset_ref: str = Field(min_length=1)
    playback_url: str = Field(min_length=1)
    content_type: str = Field(min_length=1)
    duration_seconds: int = Field(gt=0)
    reused: bool = False


class PlaybackSnapshotFetcher(Protocol):
    async def fetch(
        self, source: MusicSourceClassification, *, duration_seconds: int
    ) -> SnapshotBytes: ...


class MusicSnapshotError(ValueError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


class UnavailablePlaybackSnapshotFetcher:
    async def fetch(
        self, source: MusicSourceClassification, *, duration_seconds: int
    ) -> SnapshotBytes:
        raise MusicSnapshotError("snapshot_not_configured")


class ProviderPlaybackSnapshotFetcher:
    """Fetch complete provider playback assets through the shared request seam."""

    def __init__(
        self,
        resolver: Callable[
            [MusicSourceClassification], Awaitable[ResolvedPlaybackRequest]
        ],
        *,
        max_bytes: int = 64 * 1024 * 1024,
        timeout_seconds: float = 30.0,
        client_factory: Callable[[float], httpx.AsyncClient] | None = None,
    ) -> None:
        self.resolver = resolver
        self.max_bytes = max_bytes
        self.timeout_seconds = timeout_seconds
        self.client_factory = client_factory or _default_snapshot_client

    async def fetch(
        self, source: MusicSourceClassification, *, duration_seconds: int
    ) -> SnapshotBytes:
        from wavecast.providers.playback import ResolvedPlaybackRequest

        try:
            request = await self.resolver(source)
        except MusicSnapshotError:
            raise
        except Exception as exc:
            raise MusicSnapshotError("snapshot_provider_unavailable") from exc
        if not isinstance(request, ResolvedPlaybackRequest):
            raise MusicSnapshotError("snapshot_provider_unavailable")

        client = self.client_factory(self.timeout_seconds)
        try:
            async with client.stream(
                "GET",
                request.url,
                headers={"Accept": "audio/*", **request.headers},
                params=request.params,
            ) as response:
                if not 200 <= response.status_code < 300:
                    raise MusicSnapshotError("snapshot_upstream_status")
                content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if content_type not in MusicSnapshotStore._SUPPORTED_CONTENT_TYPES:
                    raise MusicSnapshotError("unsupported_snapshot_content_type")
                content_length = response.headers.get("content-length")
                if content_length and _is_over_limit(content_length, self.max_bytes):
                    raise MusicSnapshotError("snapshot_size_limit_exceeded")
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise MusicSnapshotError("snapshot_size_limit_exceeded")
                    chunks.append(chunk)
                if not chunks:
                    raise MusicSnapshotError("snapshot_empty_response")
                return SnapshotBytes(
                    content=b"".join(chunks),
                    content_type=content_type,
                    duration_seconds=duration_seconds,
                )
        except MusicSnapshotError:
            raise
        except httpx.TimeoutException as exc:
            raise MusicSnapshotError("snapshot_timeout") from exc
        except Exception as exc:
            raise MusicSnapshotError("snapshot_upstream_unavailable") from exc
        finally:
            await client.aclose()


def _default_snapshot_client(timeout_seconds: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True)


def _is_over_limit(value: str, max_bytes: int) -> bool:
    try:
        return int(value) > max_bytes
    except ValueError:
        return False


def _safe_path_parts(path: str) -> list[str] | None:
    decoded = unquote(path)
    if "\\" in decoded:
        return None
    parts = decoded.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return None
    return parts


def classify_music_source(source_url: str) -> MusicSourceClassification:
    parsed = urlsplit(source_url)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        return MusicSourceClassification(
            kind=MusicSourceKind.UNSUPPORTED,
            source_url=source_url,
            identity="",
            reason_code="external_or_qualified_url",
        )
    if not source_url.startswith("/"):
        return MusicSourceClassification(
            kind=MusicSourceKind.UNSUPPORTED,
            source_url=source_url,
            identity="",
            reason_code="source_path_required",
        )

    decoded = unquote(parsed.path)
    if decoded.startswith("/api/assets/audio/") and len(decoded) > len("/api/assets/audio/"):
        key = decoded.removeprefix("/api/assets/audio/")
        key_parts = _safe_path_parts(key)
        if key_parts is not None:
            return MusicSourceClassification(
                kind=MusicSourceKind.OWNED_ASSET,
                source_url=source_url,
                identity=key,
            )
        return MusicSourceClassification(
            kind=MusicSourceKind.UNSUPPORTED,
            source_url=source_url,
            identity="",
            reason_code="unsafe_owned_asset_path",
        )

    parts = _safe_path_parts(decoded.removeprefix("/"))
    if parts is None:
        return MusicSourceClassification(
            kind=MusicSourceKind.UNSUPPORTED,
            source_url=source_url,
            identity="",
            reason_code="unsafe_source_path",
        )
    if len(parts) == 5 and parts[:3] == ["api", "audio", "sidecar"]:
        provider, track_id = parts[3], parts[4]
        if provider and track_id:
            return MusicSourceClassification(
                kind=MusicSourceKind.SIDECAR_PROXY,
                source_url=source_url,
                identity=f"{provider}/{track_id}",
                provider=provider,
            )
    if len(parts) == 4 and parts[:3] == ["api", "audio", "audius"]:
        track_id = parts[3]
        if track_id:
            return MusicSourceClassification(
                kind=MusicSourceKind.AUDIUS_PROXY,
                source_url=source_url,
                identity=track_id,
                provider="audius",
            )

    return MusicSourceClassification(
        kind=MusicSourceKind.UNSUPPORTED,
        source_url=source_url,
        identity="",
        reason_code="unsupported_music_source",
    )


class MusicSnapshotStore:
    _SUPPORTED_CONTENT_TYPES = frozenset(
        {"audio/mpeg", "audio/wav", "audio/x-wav", "audio/mp4", "audio/aac"}
    )

    def __init__(
        self,
        storage: Any,
        fetcher: PlaybackSnapshotFetcher,
        *,
        max_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        self.storage = storage
        self.fetcher = fetcher
        self.max_bytes = max_bytes

    async def snapshot(
        self,
        source: MusicSourceClassification,
        *,
        track_ref: str,
        duration_seconds: int = 1,
    ) -> StoredMusicAsset:
        if source.kind is MusicSourceKind.OWNED_ASSET:
            return StoredMusicAsset(
                asset_ref=source.identity,
                playback_url=source.source_url,
                content_type="audio/mpeg",
                duration_seconds=1,
                reused=True,
            )
        if source.kind not in {MusicSourceKind.SIDECAR_PROXY, MusicSourceKind.AUDIUS_PROXY}:
            raise MusicSnapshotError(source.reason_code or "unsupported_music_source")
        provider = source.provider or "unknown"
        key = self._cache_key(source, track_ref)
        try:
            cached = await self.storage.get(key)
        except Exception as exc:
            raise MusicSnapshotError("snapshot_storage_unavailable") from exc
        if cached is not None:
            cached_result = self._cached_result(cached, key, provider, track_ref)
            if cached_result is not None:
                return cached_result

        try:
            snapshot = await self.fetcher.fetch(
                source, duration_seconds=duration_seconds
            )
        except MusicSnapshotError:
            raise
        except Exception as exc:
            raise MusicSnapshotError("snapshot_fetch_failed") from exc
        self._validate_snapshot(snapshot)
        metadata = {
            "provider": provider,
            "track_ref": track_ref,
            "content_type": snapshot.content_type,
            "duration_seconds": snapshot.duration_seconds,
            "snapshot_version": 1,
        }
        try:
            await self.storage.put(key, snapshot.content, snapshot.content_type, metadata)
            playback_url = self.storage.url_for(key)
        except Exception as exc:
            raise MusicSnapshotError("snapshot_storage_failed") from exc
        return StoredMusicAsset(
            asset_ref=key,
            playback_url=playback_url,
            content_type=snapshot.content_type,
            duration_seconds=snapshot.duration_seconds,
            reused=False,
        )

    def _cached_result(
        self, cached: Any, key: str, provider: str, track_ref: str
    ) -> StoredMusicAsset | None:
        metadata = getattr(cached, "metadata", {})
        if (
            getattr(cached, "content", b"")
            and len(getattr(cached, "content", b"")) <= self.max_bytes
            and getattr(cached, "content_type", "") in self._SUPPORTED_CONTENT_TYPES
            and isinstance(metadata, dict)
            and metadata.get("provider") == provider
            and metadata.get("track_ref") == track_ref
            and metadata.get("snapshot_version") == 1
        ):
            duration = metadata.get("duration_seconds")
            if isinstance(duration, int) and duration > 0:
                return StoredMusicAsset(
                    asset_ref=key,
                    playback_url=self.storage.url_for(key),
                    content_type=cached.content_type,
                    duration_seconds=duration,
                    reused=True,
                )
        return None

    def _validate_snapshot(self, snapshot: SnapshotBytes) -> None:
        if snapshot.content_type not in self._SUPPORTED_CONTENT_TYPES:
            raise MusicSnapshotError("unsupported_snapshot_content_type")
        if len(snapshot.content) > self.max_bytes:
            raise MusicSnapshotError("snapshot_size_limit_exceeded")

    def _cache_key(self, source: MusicSourceClassification, track_ref: str) -> str:
        identity = "\0".join(("wavecast-music-snapshot-v1", source.kind.value, source.identity, track_ref))
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        return f"music/{source.provider or 'unknown'}/{digest}.audio"
