from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from wavecast.materialization import (
    MusicSnapshotError,
    MusicSnapshotStore,
    MusicSourceKind,
    ProviderPlaybackSnapshotFetcher,
    SnapshotBytes,
    classify_music_source,
)
from wavecast.materialization.music import recoverable_music_source
from wavecast.providers.playback import ResolvedPlaybackRequest
from wavecast.storage import LocalObjectStorageProvider


class FakeFetcher:
    def __init__(self, result: SnapshotBytes | None = None) -> None:
        self.calls = 0
        self.result = result or SnapshotBytes(
            content=b"deterministic-audio",
            content_type="audio/wav",
            duration_seconds=7,
        )

    async def fetch(
        self, source: object, *, duration_seconds: int
    ) -> SnapshotBytes:
        self.calls += 1
        return self.result


@pytest.mark.parametrize("legacy", [False, True])
def test_evicted_owned_music_is_restored_from_validated_identity(tmp_path, legacy) -> None:
    async def run() -> None:
        storage = LocalObjectStorageProvider(tmp_path)
        fetcher = FakeFetcher()
        store = MusicSnapshotStore(storage, fetcher)
        source = classify_music_source("/api/audio/sidecar/netease/123")
        first = await store.snapshot(source, track_ref="netease:123")
        if legacy:
            metadata = storage.metadata_for(first.asset_ref)
            metadata.pop("source_url")
            await storage.put(first.asset_ref, b"old", "audio/wav", metadata)
        (tmp_path / first.asset_ref).unlink()
        restored = await store.snapshot(
            classify_music_source(first.playback_url), track_ref="netease:123",
            duration_seconds=7,
        )
        assert restored.asset_ref == first.asset_ref
        assert restored.playback_url == first.playback_url
        assert (await storage.get(restored.asset_ref)).content == fetcher.result.content
        assert fetcher.calls == 2
        assert recoverable_music_source(storage.metadata_for(first.asset_ref), "music/bad.audio") is None
        (tmp_path / first.asset_ref).unlink()
        fetcher.result = fetcher.result.model_copy(update={"content": b"different audio"})
        with pytest.raises(MusicSnapshotError, match="snapshot_content_changed"):
            await store.snapshot(classify_music_source(first.playback_url), track_ref="netease:123")
        assert not storage.exists(first.asset_ref)
    asyncio.run(run())


@pytest.mark.parametrize(
    ("source", "kind"),
    [
        ("/api/assets/audio/music/a.wav", MusicSourceKind.OWNED_ASSET),
        ("/api/audio/sidecar/mock/track-a", MusicSourceKind.SIDECAR_PROXY),
        ("/api/audio/audius/track-a", MusicSourceKind.AUDIUS_PROXY),
        ("https://provider.example/track-a", MusicSourceKind.UNSUPPORTED),
        ("/api/audio/sidecar/mock/track-a?token=secret", MusicSourceKind.UNSUPPORTED),
        ("/api/audio/sidecar/mock/../track-a", MusicSourceKind.UNSUPPORTED),
        ("/api/audio/sidecar/mock/track-a\\x", MusicSourceKind.UNSUPPORTED),
    ],
)
def test_classify_music_sources(source: str, kind: MusicSourceKind) -> None:
    assert classify_music_source(source).kind is kind


def test_snapshot_is_cached_by_source_identity_and_track_ref(tmp_path: Path) -> None:
    async def run() -> None:
        storage = LocalObjectStorageProvider(tmp_path / "audio")
        fetcher = FakeFetcher()
        store = MusicSnapshotStore(storage, fetcher)
        source = classify_music_source("/api/audio/sidecar/mock/track-a")

        first = await store.snapshot(source, track_ref="track-ref")
        second = await store.snapshot(source, track_ref="track-ref")

        assert first.reused is False
        assert second.reused is True
        assert second.asset_ref == first.asset_ref
        assert fetcher.calls == 1
        assert second.playback_url.startswith("/api/assets/audio/")

    asyncio.run(run())


def test_snapshot_rejects_unsupported_content_type(tmp_path: Path) -> None:
    async def run() -> None:
        storage = LocalObjectStorageProvider(tmp_path / "audio")
        fetcher = FakeFetcher(
            SnapshotBytes(content=b"audio", content_type="application/octet-stream", duration_seconds=1)
        )
        store = MusicSnapshotStore(storage, fetcher)
        source = classify_music_source("/api/audio/audius/track-a")

        with pytest.raises(MusicSnapshotError, match="unsupported_snapshot_content_type"):
            await store.snapshot(source, track_ref="track-ref")
        assert fetcher.calls == 1

    asyncio.run(run())


def test_snapshot_rejects_size_limit(tmp_path: Path) -> None:
    async def run() -> None:
        storage = LocalObjectStorageProvider(tmp_path / "audio")
        fetcher = FakeFetcher(
            SnapshotBytes(content=b"0123456789", content_type="audio/wav", duration_seconds=1)
        )
        store = MusicSnapshotStore(storage, fetcher, max_bytes=4)
        source = classify_music_source("/api/audio/sidecar/mock/track-a")

        with pytest.raises(MusicSnapshotError, match="snapshot_size_limit_exceeded"):
            await store.snapshot(source, track_ref="track-ref")

    asyncio.run(run())


def test_provider_snapshot_fetcher_uses_shared_request_and_segment_duration() -> None:
    async def run() -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                headers={"content-type": "audio/mpeg; charset=utf-8"},
                content=b"full-track",
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        async def resolve(_source: object) -> ResolvedPlaybackRequest:
            return ResolvedPlaybackRequest(
                provider="audius",
                url="https://upstream.example.test/tracks/track-1/stream",
                headers={"Authorization": "Bearer server-only"},
                params={"api_key": "app-key"},
            )

        fetcher = ProviderPlaybackSnapshotFetcher(
            resolve,
            client_factory=lambda _timeout: client,
        )
        snapshot = await fetcher.fetch(
            classify_music_source("/api/audio/audius/track-1"),
            duration_seconds=184,
        )

        assert snapshot.content == b"full-track"
        assert snapshot.content_type == "audio/mpeg"
        assert snapshot.duration_seconds == 184
        assert len(requests) == 1
        assert requests[0].url.params["api_key"] == "app-key"
        assert requests[0].headers["authorization"] == "Bearer server-only"
        assert requests[0].headers["accept"] == "audio/*"
        assert "range" not in requests[0].headers

    asyncio.run(run())


class _TrackedChunks(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.yielded = 0

    async def __aiter__(self):
        for chunk in self.chunks:
            self.yielded += 1
            yield chunk

    async def aclose(self) -> None:
        pass


async def _fetch_snapshot_response(
    response: httpx.Response, *, max_bytes: int = 4
) -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: response)
    )

    async def resolve(_source: object) -> ResolvedPlaybackRequest:
        return ResolvedPlaybackRequest(
            provider="test",
            url="https://upstream.example.test/audio",
        )

    fetcher = ProviderPlaybackSnapshotFetcher(
        resolve,
        max_bytes=max_bytes,
        client_factory=lambda _timeout: client,
    )
    await fetcher.fetch(
        classify_music_source("/api/audio/sidecar/netease/track-1"),
        duration_seconds=7,
    )


def test_provider_snapshot_fetcher_rejects_content_length_before_consuming_body() -> None:
    async def run() -> None:
        body = _TrackedChunks([b"not-read"])
        response = httpx.Response(
            200,
            headers={
                "content-type": "audio/mpeg",
                "content-length": "5",
            },
            stream=body,
        )
        with pytest.raises(MusicSnapshotError, match="snapshot_size_limit_exceeded"):
            await _fetch_snapshot_response(response)
        assert body.yielded == 0

    asyncio.run(run())


def test_provider_snapshot_fetcher_enforces_stream_limit_without_content_length() -> None:
    async def run() -> None:
        body = _TrackedChunks([b"123", b"456", b"789"])
        response = httpx.Response(
            200,
            headers={"content-type": "audio/mpeg"},
            stream=body,
        )
        with pytest.raises(MusicSnapshotError, match="snapshot_size_limit_exceeded"):
            await _fetch_snapshot_response(response)
        assert body.yielded == 2

    asyncio.run(run())


@pytest.mark.parametrize(
    ("status_code", "content_type", "expected_reason"),
    [
        (200, "audio/mpeg", "snapshot_empty_response"),
        (503, "audio/mpeg", "snapshot_upstream_status"),
        (200, "application/octet-stream", "unsupported_snapshot_content_type"),
    ],
)
def test_provider_snapshot_fetcher_maps_response_boundaries(
    status_code: int, content_type: str, expected_reason: str
) -> None:
    async def run() -> None:
        response = httpx.Response(
            status_code,
            headers={"content-type": content_type},
            content=b"" if status_code == 200 and content_type == "audio/mpeg" else b"body",
        )
        with pytest.raises(MusicSnapshotError, match=expected_reason):
            await _fetch_snapshot_response(response)

    asyncio.run(run())


def test_provider_snapshot_fetcher_maps_timeout() -> None:
    async def run() -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("upstream timeout")

        response = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=response)

        async def resolve(_source: object) -> ResolvedPlaybackRequest:
            return ResolvedPlaybackRequest(
                provider="test",
                url="https://upstream.example.test/audio",
            )

        fetcher = ProviderPlaybackSnapshotFetcher(
            resolve,
            client_factory=lambda _timeout: client,
        )
        with pytest.raises(MusicSnapshotError, match="snapshot_timeout"):
            await fetcher.fetch(
                classify_music_source("/api/audio/sidecar/netease/track-1"),
                duration_seconds=7,
            )

    asyncio.run(run())
