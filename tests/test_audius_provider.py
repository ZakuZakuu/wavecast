import asyncio

import httpx
from wavecast.intelligence.models import ResolvedTrack, TrackProposal
from wavecast.intelligence.resolution import resolve_track_proposal
from wavecast.providers.audius import AudiusMusicProvider
from wavecast.providers.config import ProviderSettings
from wavecast.providers.contracts import AudioAssetType


def test_audius_adapter_normalizes_search_resolution_and_stream_asset() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/tracks/search"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "track-1",
                            "title": "Open Water",
                            "duration": 184,
                            "user": {"name": "Signal Artist"},
                            "genre": "Electronic",
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "data": {
                    "id": "track-1",
                    "title": "Open Water",
                    "duration": 184,
                    "user": {"name": "Signal Artist"},
                    "genre": "Electronic",
                }
            },
        )

    async def run() -> tuple[object, object, object]:
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="https://audius.test"
        )
        provider = AudiusMusicProvider(
            ProviderSettings(audius_api_key="app-key"),
            client=client,
            base_url="https://audius.test/v1",
        )
        tracks = await provider.search("Signal Artist Open Water", limit=1)
        resolved = await resolve_track_proposal(
            provider,
            TrackProposal(artist="Signal Artist", title="Open Water", confidence=0.9)
        )
        asset = await provider.get_playback_asset(resolved) if resolved else None
        await client.aclose()
        return tracks, resolved, asset

    tracks, resolved, asset = asyncio.run(run())

    assert len(tracks) == 1
    assert tracks[0].track_ref == "audius:track-1"
    assert tracks[0].metadata["genre"] == "Electronic"
    assert resolved is not None
    assert resolved.track_ref == "audius:track-1"
    assert asset is not None
    assert asset.asset_type is AudioAssetType.MUSIC
    assert asset.playback_url == "/api/audio/audius/track-1"
    assert all(request.headers.get("authorization") is None for request in requests)
    assert all(request.url.params["api_key"] == "app-key" for request in requests)
    assert [request.url.path for request in requests] == [
        "/v1/tracks/search",
        "/v1/tracks/search",
        "/v1/tracks/track-1",
    ]


def test_audius_adapter_does_not_mark_missing_duration_as_playable() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [{"id": "track-2", "title": "No Duration", "user": {"name": "Artist"}}]},
        )

    async def run() -> bool:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = AudiusMusicProvider(ProviderSettings(), client=client)
        result = await provider.search("No Duration")
        await client.aclose()
        return result[0].playable

    assert asyncio.run(run()) is False


def test_audius_bearer_is_backend_only_and_distinct_from_api_key() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "data": {
                    "id": "track-1",
                    "title": "Open Water",
                    "duration": 184,
                    "user": {"name": "Signal Artist"},
                }
            },
        )

    async def run() -> object:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = AudiusMusicProvider(
            ProviderSettings(
                audius_api_key="app-key",
                audius_bearer_token="server-bearer",
            ),
            client=client,
        )
        asset = await provider.get_playback_asset(
            ResolvedTrack(
                track_ref="audius:track-1",
                canonical_artist="Signal Artist",
                canonical_title="Open Water",
            )
        )
        await client.aclose()
        return asset

    asset = asyncio.run(run())

    assert asset.playback_url == "/api/audio/audius/track-1"
    assert requests[0].headers["authorization"] == "Bearer server-bearer"
    assert requests[0].url.params["api_key"] == "app-key"
    assert "server-bearer" not in asset.playback_url
    assert "app-key" not in asset.playback_url
