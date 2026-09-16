from collections.abc import AsyncIterator
from types import SimpleNamespace

import httpx
import pytest

import services.api.main as api_module


@pytest.mark.asyncio
async def test_audius_proxy_returns_503_without_live_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WAVECAST_PROVIDER_MODE", "mock")
    monkeypatch.delenv("AUDIUS_API_KEY", raising=False)
    monkeypatch.delenv("AUDIUS_BEARER_TOKEN", raising=False)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api_module.app), base_url="http://test"
    ) as browser:
        response = await browser.get("/api/audio/audius/track-1")

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_audius_proxy_preserves_range_response_and_hides_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WAVECAST_PROVIDER_MODE", "live")
    monkeypatch.setenv("AUDIUS_API_KEY", "app-key")
    monkeypatch.setenv("AUDIUS_BEARER_TOKEN", "server-bearer")

    upstream = _FakeUpstream()
    client = _FakeClient(upstream)
    monkeypatch.setattr(
        api_module, "httpx", SimpleNamespace(AsyncClient=lambda **_: client)
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api_module.app), base_url="http://test"
    ) as browser:
        response = await browser.get(
            "/api/audio/audius/track-1",
            headers={"Range": "bytes=0-3", "If-Range": "etag-1"},
        )

    assert response.status_code == 206
    assert response.headers["content-range"] == "bytes 0-3/10"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-length"] == "4"
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.content == b"raw"

    assert client.request is not None
    assert client.request.url.params["api_key"] == "app-key"
    assert client.request.headers["authorization"] == "Bearer server-bearer"
    assert client.request.headers["range"] == "bytes=0-3"
    assert client.request.headers["if-range"] == "etag-1"
    assert "app-key" not in str(response.url)
    assert "server-bearer" not in str(response.url)
    assert all(
        secret not in value
        for secret in ("app-key", "server-bearer")
        for value in response.headers.values()
    )
    assert b"app-key" not in response.content
    assert b"server-bearer" not in response.content
    assert upstream.closed
    assert client.closed


class _FakeUpstream:
    status_code = 206
    headers = {
        "content-range": "bytes 0-3/10",
        "accept-ranges": "bytes",
        "content-length": "4",
        "content-type": "audio/mpeg",
    }

    def __init__(self) -> None:
        self.closed = False

    async def aiter_raw(self) -> AsyncIterator[bytes]:
        yield b"raw"

    async def aiter_bytes(self) -> AsyncIterator[bytes]:
        raise AssertionError("proxy must stream raw upstream bytes")
        yield b"unreachable"

    async def aclose(self) -> None:
        self.closed = True


class _FakeClient:
    def __init__(self, upstream: _FakeUpstream) -> None:
        self.upstream = upstream
        self.request: httpx.Request | None = None
        self.closed = False

    def build_request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str],
        headers: dict[str, str],
    ) -> httpx.Request:
        return httpx.Request(method, url, params=params, headers=headers)

    async def send(self, request: httpx.Request, *, stream: bool) -> _FakeUpstream:
        assert stream is True
        self.request = request
        return self.upstream

    async def aclose(self) -> None:
        self.closed = True
