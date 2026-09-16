import asyncio

import httpx
import pytest
from wavecast.providers.config import ProviderSettings
from wavecast.providers.errors import ProviderConfigurationError, ProviderInvalidResponseError
from wavecast.providers.minimax import MiniMaxTTSProvider
from wavecast.providers.usage import UsageLedger
from wavecast.storage import LocalObjectStorageProvider


def settings() -> ProviderSettings:
    return ProviderSettings(
        mode="live",
        minimax_api_key="minimax-secret",
        minimax_tts_voice_id="test-voice",
    )


def test_minimax_mock_mode_does_not_require_credentials(tmp_path) -> None:
    async def run() -> None:
        provider = MiniMaxTTSProvider(
            ProviderSettings(mode="mock"),
            storage=LocalObjectStorageProvider(tmp_path / "audio"),
        )
        with pytest.raises(ProviderConfigurationError):
            await provider.synthesize("No live call", cues=[])
        await provider.aclose()

    asyncio.run(run())


def test_tts_cache_key_is_stable_and_cue_sensitive(tmp_path) -> None:
    provider = MiniMaxTTSProvider(
        settings(), storage=LocalObjectStorageProvider(tmp_path / "audio")
    )

    first = provider.cache_key("Same text", ["pause_short"])
    second = provider.cache_key("Same text", ["pause_short"])
    changed = provider.cache_key("Same text", ["pause_long"])

    assert first == second
    assert first.endswith(".mp3")
    assert first != changed


def test_minimax_payload_decodes_hex_and_records_usage(tmp_path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "base_resp": {"status_code": 0, "status_msg": "success"},
                "data": {"audio": "00010203", "status": 2},
                "extra_info": {
                    "audio_length": 2052,
                    "audio_format": "mp3",
                    "usage_characters": 12,
                },
            },
        )

    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        ledger = UsageLedger()
        storage = LocalObjectStorageProvider(tmp_path / "audio")
        provider = MiniMaxTTSProvider(settings(), storage=storage, ledger=ledger, client=client)
        asset = await provider.synthesize("Hello, listener.", cues=["pause_short"])
        await client.aclose()
        return asset, ledger

    asset, ledger = asyncio.run(run())
    request = requests[0]
    assert request.url.path == "/v1/t2a_v2"
    assert request.headers["authorization"] == "Bearer minimax-secret"
    payload = request.content.decode()
    assert '"model":"speech-2.8-hd"' in payload
    assert '"stream":false' in payload
    assert '"output_format":"hex"' in payload
    assert '"voice_id":"test-voice"' in payload
    assert '"sample_rate":32000' in payload
    assert asset.playback_url.startswith("/api/assets/audio/")
    assert asset.duration == 3
    assert ledger.events[0].provider == "minimax"
    assert ledger.events[0].operation == "tts"
    assert ledger.events[0].usage_characters == 12
    assert "minimax-secret" not in asset.playback_url


@pytest.mark.parametrize(
    "payload",
    [
        {"base_resp": {"status_code": 0}, "data": None},
        {"base_resp": {"status_code": 0}, "data": {"audio": None}},
        {"base_resp": {"status_code": 0}, "data": {"audio": "not-hex"}},
        {
            "base_resp": {"status_code": 0},
            "data": {"audio": "00"},
            "extra_info": "invalid",
        },
    ],
)
def test_minimax_rejects_malformed_responses(tmp_path, payload) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async def run() -> UsageLedger:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        ledger = UsageLedger()
        provider = MiniMaxTTSProvider(
            settings(),
            storage=LocalObjectStorageProvider(tmp_path / "audio"),
            ledger=ledger,
            client=client,
        )
        with pytest.raises(ProviderInvalidResponseError):
            await provider.synthesize("Hello", cues=[])
        await client.aclose()
        return ledger

    ledger = asyncio.run(run())
    assert ledger.events[-1].metadata["success"] is False


def test_minimax_cache_hit_does_not_make_second_request(tmp_path) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "base_resp": {"status_code": 0},
                "data": {"audio": "00010203"},
                "extra_info": {"audio_length": 1000, "audio_format": "mp3"},
            },
        )

    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        storage = LocalObjectStorageProvider(tmp_path / "audio")
        provider = MiniMaxTTSProvider(settings(), storage=storage, client=client)
        first = await provider.synthesize("Same text", cues=[])
        second = await provider.synthesize("Same text", cues=[])
        await client.aclose()
        return first, second

    first, second = asyncio.run(run())
    assert calls == 1
    assert first.asset_id == second.asset_id
