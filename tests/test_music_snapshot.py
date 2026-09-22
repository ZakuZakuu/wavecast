from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from wavecast.materialization import (
    MusicSnapshotError,
    MusicSnapshotStore,
    MusicSourceKind,
    SnapshotBytes,
    classify_music_source,
)
from wavecast.storage import LocalObjectStorageProvider


class FakeFetcher:
    def __init__(self, result: SnapshotBytes | None = None) -> None:
        self.calls = 0
        self.result = result or SnapshotBytes(
            content=b"deterministic-audio",
            content_type="audio/wav",
            duration_seconds=7,
        )

    async def fetch(self, source: object) -> SnapshotBytes:
        self.calls += 1
        return self.result


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
