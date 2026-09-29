import asyncio
import json

import httpx
import pytest
from wavecast.intelligence.models import ResolvedTrack
from wavecast.providers.config import ProviderSettings
from wavecast.providers.contracts import AudioAssetType
from wavecast.providers.errors import ProviderConfigurationError
from wavecast.providers.netease import NeteaseMusicProvider
from wavecast.providers.qqmusic import QQMusicProvider


def test_sidecar_adapters_are_optional_in_mock_mode() -> None:
    with pytest.raises(ProviderConfigurationError):
        NeteaseMusicProvider(ProviderSettings())
    with pytest.raises(ProviderConfigurationError):
        QQMusicProvider(ProviderSettings())


@pytest.mark.parametrize(
    ("provider_type", "provider_name", "base_url"),
    [
        (NeteaseMusicProvider, "netease", "https://netease.sidecar"),
        (QQMusicProvider, "qqmusic", "https://qqmusic.sidecar"),
    ],
)
def test_sidecar_adapters_use_provider_neutral_http_contract(
    provider_type: type[NeteaseMusicProvider] | type[QQMusicProvider],
    provider_name: str,
    base_url: str,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/search":
            return httpx.Response(
                200,
                json={
                    "tracks": [
                        {
                            "id": "track-1",
                            "artist": "Signal Artist",
                            "title": "Open Water",
                            "album": "Night Signals",
                            "duration_seconds": 184,
                        }
                    ]
                },
            )
        if request.url.path == "/tracks/track-1":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "id": "track-1",
                        "artist": "Signal Artist",
                        "title": "Open Water",
                        "album": "Night Signals",
                        "duration_seconds": 184,
                    }
                },
            )
        return httpx.Response(
            200,
            json={"data": {"playback_url": f"{base_url}/stream/track-1"}},
        )

    async def run() -> tuple[list[object], object]:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=base_url)
        provider = provider_type(
            ProviderSettings(),
            client=client,
            base_url=base_url,
        )
        tracks = await provider.search("Signal Artist Open Water", limit=1)
        asset = await provider.get_playback_asset(
            ResolvedTrack(
                track_ref=f"{provider_name}:track-1",
                canonical_artist="Signal Artist",
                canonical_title="Open Water",
            )
        )
        await client.aclose()
        return tracks, asset

    tracks, asset = asyncio.run(run())

    assert len(tracks) == 1
    assert tracks[0].track_ref == f"{provider_name}:track-1"
    assert tracks[0].metadata["album"] == "Night Signals"
    assert asset.asset_type is AudioAssetType.MUSIC
    assert asset.provider == provider_name
    assert asset.playback_url == f"/api/audio/sidecar/{provider_name}/track-1"
    assert base_url not in json.dumps(asset.model_dump(mode="json"))
    assert [request.url.path for request in requests] == [
        "/search",
        "/tracks/track-1",
        "/tracks/track-1/playback",
    ]


def test_netease_sidecar_exposes_optional_timing_profile() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/tracks/track-1/timing"
        return httpx.Response(
            200,
            json={
                "source_duration_seconds": 184,
                "lyric_timestamps_available": True,
                "lyric_lines": [{"start_seconds": 4.0, "end_seconds": 8.0}],
                "vocal_intervals": [{"start_seconds": 4.0, "end_seconds": 8.0}],
            },
        )

    async def run():
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://netease.sidecar",
        )
        provider = NeteaseMusicProvider(
            ProviderSettings(),
            client=client,
            base_url="https://netease.sidecar",
        )
        profile = await provider.get_timing_profile("netease:track-1")
        await client.aclose()
        return profile

    profile = asyncio.run(run())

    assert profile is not None
    assert profile.source_duration_seconds == 184
    assert profile.first_vocal_start_seconds == 4
    assert profile.last_vocal_end_seconds == 8
