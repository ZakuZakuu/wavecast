from collections.abc import AsyncIterator
from types import SimpleNamespace

import httpx
import pytest

import services.api.main as api_module


class FakeSidecar:
    def __init__(self) -> None:
        self.track_refs: list[str] = []
        self.closed = False

    async def resolve_upstream_playback_url(self, track_ref: str) -> str:
        self.track_refs.append(track_ref)
        return "https://upstream.example.test/stream/track-1"

    async def aclose(self) -> None:
        self.closed = True


class FakeUpstream:
    status_code = 206
    headers = {
        "content-range": "bytes 0-3/10",
        "accept-ranges": "bytes",
        "content-length": "4",
        "content-type": "audio/mpeg",
    }

    async def aiter_raw(self) -> AsyncIterator[bytes]:
        yield b"raw"

    async def aclose(self) -> None:
        pass


class FakeClient:
    def __init__(self, upstream: FakeUpstream) -> None:
        self.upstream = upstream
        self.request: httpx.Request | None = None

    def build_request(
        self, method: str, url: str, *, headers: dict[str, str]
    ) -> httpx.Request:
        return httpx.Request(method, url, headers=headers)

    async def send(self, request: httpx.Request, *, stream: bool) -> FakeUpstream:
        assert stream is True
        self.request = request
        return self.upstream

    async def aclose(self) -> None:
        pass


@pytest.mark.asyncio
async def test_sidecar_proxy_hides_upstream_url_and_preserves_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sidecar = FakeSidecar()
    upstream = FakeUpstream()
    client = FakeClient(upstream)
    monkeypatch.setattr(api_module, "_build_sidecar_provider", lambda _: sidecar)
    monkeypatch.setattr(
        api_module,
        "httpx",
        SimpleNamespace(AsyncClient=lambda **_: client),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api_module.app), base_url="http://test"
    ) as browser:
        response = await browser.get(
            "/api/audio/sidecar/netease/track-1",
            headers={"Range": "bytes=0-3", "If-Range": "etag-1"},
        )

    assert response.status_code == 206
    assert response.headers["content-range"] == "bytes 0-3/10"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-length"] == "4"
    assert response.content == b"raw"
    assert sidecar.track_refs == ["netease:track-1"]
    assert sidecar.closed
    assert client.request is not None
    assert str(client.request.url) == "https://upstream.example.test/stream/track-1"
    assert client.request.headers["range"] == "bytes=0-3"
    assert client.request.headers["if-range"] == "etag-1"
    assert "upstream.example.test" not in str(response.url)


@pytest.mark.asyncio
async def test_sidecar_playback_resolution_is_reused_for_nearby_range_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sidecar = FakeSidecar()
    api_module._playback_request_cache.clear()
    monkeypatch.setattr(api_module, "_build_sidecar_provider", lambda _: sidecar)

    try:
        first = await api_module._resolve_sidecar_playback_request(
            "netease",
            "track-cache",
        )
        second = await api_module._resolve_sidecar_playback_request(
            "netease",
            "track-cache",
        )
    finally:
        api_module._playback_request_cache.clear()

    assert first == second
    assert sidecar.track_refs == ["netease:track-cache"]
    assert sidecar.closed is True
