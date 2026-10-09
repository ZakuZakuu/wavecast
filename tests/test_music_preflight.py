from __future__ import annotations

import asyncio
from argparse import Namespace
from pathlib import Path

import httpx
import pytest
from wavecast.providers.config import ProviderSettings
from wavecast.providers.contracts import TrackMetadata
from wavecast.providers.registry import MusicProviderRegistry

from scripts import live_episode_probe
from scripts.music_preflight import MusicPreflightError, MusicPreflightResult, preflight_music


class FixtureCatalog:
    def __init__(self, tracks: list[TrackMetadata]) -> None:
        self.tracks = tracks
        self.search_calls = 0

    async def search(self, query: str, *, limit: int = 5) -> list[TrackMetadata]:
        del query
        self.search_calls += 1
        return self.tracks[:limit]

    async def resolve_track(self, track_ref: str) -> TrackMetadata:
        return next(track for track in self.tracks if track.track_ref == track_ref)

    async def get_playback_asset(self, resolved_track: object) -> object:
        del resolved_track
        raise AssertionError("preflight must not request playback assets")


def _settings() -> ProviderSettings:
    return ProviderSettings(mode="live", netease_music_api_base_url="http://sidecar.test")


def _ready_client(status_code: int) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/ready"
        return httpx.Response(status_code)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://sidecar.test")


def _track() -> TrackMetadata:
    return TrackMetadata(
        track_ref="netease:anchor",
        title="何なんw",
        artist="藤井風",
        duration_seconds=180,
        playable=True,
    )


def test_music_preflight_resolves_required_anchor_after_sidecar_ready() -> None:
    catalog = FixtureCatalog([_track()])
    registry = MusicProviderRegistry({"netease": catalog})
    client = _ready_client(200)

    async def run() -> MusicPreflightResult:
        try:
            return await preflight_music(
                _settings(),
                ["藤井風 — 何なんw"],
                registry=registry,
                readiness_client=client,
            )
        finally:
            await client.aclose()

    result = asyncio.run(run())
    assert result.ready is True
    assert result.resolved_anchors[0].track_ref == "netease:anchor"
    assert catalog.search_calls == 1


def test_music_preflight_rejects_sidecar_before_catalog_resolution() -> None:
    catalog = FixtureCatalog([_track()])
    registry = MusicProviderRegistry({"netease": catalog})
    client = _ready_client(503)

    async def run() -> None:
        try:
            with pytest.raises(MusicPreflightError, match="HTTP 503"):
                await preflight_music(
                    _settings(),
                    ["藤井風 — 何なんw"],
                    registry=registry,
                    readiness_client=client,
                )
        finally:
            await client.aclose()

    asyncio.run(run())
    assert catalog.search_calls == 0


def test_music_preflight_rejects_unresolved_anchor_without_playback_call() -> None:
    catalog = FixtureCatalog([])
    registry = MusicProviderRegistry({"netease": catalog})
    client = _ready_client(200)

    async def run() -> None:
        try:
            with pytest.raises(MusicPreflightError, match="could not resolve required anchor"):
                await preflight_music(
                    _settings(),
                    ["藤井風 — 何なんw"],
                    registry=registry,
                    readiness_client=client,
                )
        finally:
            await client.aclose()

    asyncio.run(run())
    assert catalog.search_calls == 2


def test_live_probe_aborts_before_assembly_when_music_preflight_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = _settings()
    assembly_called = False

    async def failing_preflight(*args: object, **kwargs: object) -> MusicPreflightResult:
        raise MusicPreflightError("music sidecar readiness is unavailable")

    def fail_if_assembly_created(_: ProviderSettings) -> object:
        nonlocal assembly_called
        assembly_called = True
        raise AssertionError("paid provider assembly must not be constructed")

    monkeypatch.setattr(live_episode_probe.ProviderSettings, "from_env", lambda: settings)
    monkeypatch.setattr(live_episode_probe, "preflight_music", failing_preflight)
    monkeypatch.setattr(
        live_episode_probe, "create_episode_assembly_service", fail_if_assembly_created
    )
    report_path = tmp_path / "preflight.json"

    result = asyncio.run(
        live_episode_probe._run(
            Namespace(
                topic="fixture",
                anchor=["藤井風 — 何なんw"],
                max_tracks=4,
                max_chapters=16,
                json_output=report_path,
            )
        )
    )

    assert result == 2
    assert assembly_called is False
    assert report_path.read_text() == (
        '{"status": "preflight_failed", "stage": "music_readiness", '
        '"reason": "music sidecar readiness is unavailable"}\n'
    )


def test_live_probe_continues_after_successful_music_preflight(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = _settings()
    assembly_calls = 0
    assembled = object()

    async def passing_preflight(*args: object, **kwargs: object) -> MusicPreflightResult:
        return MusicPreflightResult(ready=True, resolved_anchors=())

    class FakeAssembly:
        async def assemble(self, *args: object, **kwargs: object) -> object:
            return assembled

        async def aclose(self) -> None:
            return None

    def create(_: ProviderSettings) -> FakeAssembly:
        nonlocal assembly_calls
        assembly_calls += 1
        return FakeAssembly()

    monkeypatch.setattr(live_episode_probe.ProviderSettings, "from_env", lambda: settings)
    monkeypatch.setattr(live_episode_probe, "preflight_music", passing_preflight)
    monkeypatch.setattr(live_episode_probe, "create_episode_assembly_service", create)
    monkeypatch.setattr(live_episode_probe, "_report", lambda result: {"status": "ok"})
    report_path = tmp_path / "success.json"

    result = asyncio.run(
        live_episode_probe._run(
            Namespace(
                topic="fixture",
                anchor=[],
                max_tracks=4,
                max_chapters=16,
                json_output=report_path,
            )
        )
    )

    assert result == 0
    assert assembly_calls == 1
    assert '"status": "ok"' in report_path.read_text()


@pytest.mark.parametrize("token", [None, "test-gateway-token"])
def test_music_preflight_uses_optional_gateway_bearer(token: str | None) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.url.path == "/ready"
        assert request.headers.get("Authorization") == (f"Bearer {token}" if token else None)
        return httpx.Response(200)

    async def run() -> MusicPreflightResult:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await preflight_music(
                ProviderSettings(
                    netease_music_api_base_url="https://gateway.example",
                    netease_music_api_bearer_token=token,
                ),
                [],
                registry=MusicProviderRegistry({"netease": FixtureCatalog([])}),
                readiness_client=client,
            )

    assert asyncio.run(run()).ready
    assert len(calls) == 1
