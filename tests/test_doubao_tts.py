"""Doubao's single-voice speech behind the TTSProvider contract, over a faked network.

The wire format below is the one the 2026-10-16 verification run saw: JSON chunks with ``code`` 0 and
base64 PCM, then ``code`` 20000000 with ``usage.text_words``.  No real service is called.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import subprocess
import sys
import wave
from pathlib import Path
from typing import Any

import httpx
import pytest
from wavecast.providers.config import ProviderSettings
from wavecast.providers.doubao_tts import (
    DOUBAO_TTS_ENDPOINT,
    DoubaoTTSProvider,
    price_for,
    speech_rate_for,
)
from wavecast.providers.errors import (
    ProviderConfigurationError,
    ProviderIncompleteResponseError,
    ProviderInvalidResponseError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from wavecast.providers.minimax import MiniMaxTTSProvider
from wavecast.providers.tts_factory import build_tts_provider
from wavecast.providers.usage import UsageLedger
from wavecast.speech import SpeechProfile
from wavecast.storage import LocalObjectStorageProvider

REPO = Path(__file__).resolve().parents[1]
TEXT = "先来听这一首，欢迎收听 FM 九七四。"


def settings(**overrides: Any) -> ProviderSettings:
    return ProviderSettings(mode="live", tts_provider="doubao", doubao_tts_api_key="k-secret", **overrides)


def pcm(seconds: float) -> bytes:
    return b"\x01\x00" * int(24000 * seconds)


def stream(*chunks: bytes, text_words: int | None = 81, end: bool = True) -> bytes:
    lines = [json.dumps({"code": 0, "message": "", "data": base64.b64encode(chunks[0]).decode()})]
    lines.append(json.dumps({"code": 0, "message": "", "sentence": {"text": "ignored"}}))
    lines += [json.dumps({"code": 0, "message": "", "data": base64.b64encode(c).decode()}) for c in chunks[1:]]
    if end:
        done: dict[str, Any] = {"code": 20000000, "message": "ok", "data": None}
        if text_words is not None:
            done["usage"] = {"text_words": text_words}
        lines.append(json.dumps(done))
    return "\n".join(lines).encode()


class Rig:
    def __init__(self, tmp_path: Path, handler: Any, **overrides: Any) -> None:
        self.requests: list[httpx.Request] = []

        async def recording(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return await handler(request) if asyncio.iscoroutinefunction(handler) else handler(request)

        self.client = httpx.AsyncClient(transport=httpx.MockTransport(recording))
        self.ledger = UsageLedger()
        self.storage = LocalObjectStorageProvider(tmp_path / "audio")
        self.provider = DoubaoTTSProvider(
            settings(**overrides), storage=self.storage, ledger=self.ledger, client=self.client
        )

    def events(self) -> list[Any]:
        return list(self.ledger.events)


def run(rig: Rig, text: str = TEXT, **kwargs: Any) -> Any:
    async def go() -> Any:
        try:
            return await rig.provider.synthesize(text, cues=kwargs.pop("cues", []), **kwargs)
        finally:
            await rig.client.aclose()

    return asyncio.run(go())


def test_a_complete_reply_is_stored_as_wav_and_priced_from_the_billed_characters(tmp_path) -> None:  # type: ignore[no-untyped-def]
    rig = Rig(tmp_path, lambda _r: httpx.Response(200, content=stream(pcm(1.0), pcm(0.5))))

    asset = run(rig)

    request = rig.requests[0]
    body = json.loads(request.content)
    assert str(request.url) == DOUBAO_TTS_ENDPOINT
    assert request.headers["x-api-key"] == "k-secret"
    assert request.headers["x-api-resource-id"] == "seed-tts-2.0"
    assert request.headers["x-control-require-usage-tokens-return"] == "*"
    assert body["req_params"]["speaker"] == "zh_male_liufei_uranus_bigtts"
    assert body["req_params"]["audio_params"] == {"format": "pcm", "sample_rate": 24000, "speech_rate": 0}
    assert asset.duration == 2  # 1.5 s, to the nearest second
    stored = asyncio.run(rig.storage.get(asset.asset_id))
    with wave.open(io.BytesIO(stored.content)) as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (24000, 1, 2)
        assert wav.getnframes() == 36000  # both chunks, in order
    (event,) = rig.events()
    assert event.provider == "doubao_tts" and event.usage_characters == 81
    assert event.metadata["outcome"] == "ok" and event.metadata["billed_characters"] == 81
    assert event.metadata["estimated_cost_cny"] == pytest.approx(0.0243)  # 81 characters at 3 CNY / 10,000
    assert event.metadata["cost_basis"] == "reported_text_words"
    assert "k-secret" not in json.dumps(event.model_dump(mode="json"))


def test_http_200_without_the_completion_code_is_not_a_success(tmp_path) -> None:  # type: ignore[no-untyped-def]
    rig = Rig(tmp_path, lambda _r: httpx.Response(200, content=stream(pcm(1.0), end=False)))

    with pytest.raises(ProviderIncompleteResponseError):
        run(rig)

    assert len(rig.requests) == 1  # no retry
    assert asyncio.run(rig.storage.get(rig.provider.cache_key(TEXT, []))) is None  # nothing stored
    (event,) = rig.events()
    assert event.metadata["outcome"] == "ProviderIncompleteResponseError"
    assert event.metadata["estimated_cost_cny"] is None  # the receipt never arrived: unknown, not zero
    assert event.metadata["cost_basis"] == "usage_missing"


def test_a_service_error_code_in_the_stream_fails_and_is_recorded(tmp_path) -> None:  # type: ignore[no-untyped-def]
    body = json.dumps({"code": 45000010, "message": "text too long"}).encode()
    rig = Rig(tmp_path, lambda _r: httpx.Response(200, content=body))

    with pytest.raises(ProviderInvalidResponseError) as failure:
        run(rig)

    assert "45000010" in str(failure.value) and "text too long" not in str(failure.value)
    (event,) = rig.events()
    assert event.metadata["outcome"] == "ProviderInvalidResponseError"
    assert event.metadata["failed_stage"] == "request"


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(429), ProviderRateLimitError),
        (httpx.Response(503), ProviderUnavailableError),
        (httpx.ReadTimeout("slow"), ProviderTimeoutError),
    ],
)
def test_http_failures_are_mapped_recorded_and_never_retried(tmp_path, response, error) -> None:  # type: ignore[no-untyped-def]
    def handler(_request: httpx.Request) -> httpx.Response:
        if isinstance(response, Exception):
            raise response
        return response

    rig = Rig(tmp_path, handler)

    with pytest.raises(error):
        run(rig)

    assert len(rig.requests) == 1
    (event,) = rig.events()
    assert event.metadata["outcome"] == error.__name__ and event.provider == "doubao_tts"


def test_a_cancelled_call_records_a_final_event_and_the_cancellation_propagates(tmp_path) -> None:  # type: ignore[no-untyped-def]
    async def never(_request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(30)
        return httpx.Response(200)

    rig = Rig(tmp_path, never)

    async def scenario() -> bool:
        task = asyncio.create_task(rig.provider.synthesize(TEXT, cues=[]))
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            return True
        finally:
            await rig.client.aclose()
        return False

    assert asyncio.run(scenario()) is True
    (event,) = rig.events()
    assert event.metadata["outcome"] == "cancelled"
    assert event.metadata["estimated_cost_cny"] is None  # unknown, not zero


def test_a_cache_hit_makes_no_request_and_is_recorded_as_a_known_zero(tmp_path) -> None:  # type: ignore[no-untyped-def]
    rig = Rig(tmp_path, lambda _r: httpx.Response(200, content=stream(pcm(1.0))))

    async def twice() -> tuple[Any, Any]:
        first = await rig.provider.synthesize(TEXT, cues=["breath"])
        second = await rig.provider.synthesize(TEXT, cues=["breath"])
        await rig.client.aclose()
        return first, second

    first, second = asyncio.run(twice())

    assert len(rig.requests) == 1  # the same line is not paid for twice
    assert first.asset_id == second.asset_id and second.metadata["cache_hit"] is True
    paid, cached = rig.events()
    assert paid.metadata["cache_hit"] is False and paid.metadata["estimated_cost_cny"] == pytest.approx(0.0243)
    assert cached.metadata["cache_hit"] is True and cached.metadata["estimated_cost_cny"] == 0.0
    assert cached.metadata["cost_basis"] == "cache_hit"


def test_the_cache_key_covers_vendor_voice_rate_and_text_and_never_matches_minimax(tmp_path) -> None:  # type: ignore[no-untyped-def]
    storage = LocalObjectStorageProvider(tmp_path / "audio")
    base = DoubaoTTSProvider(settings(), storage=storage)
    other_voice = DoubaoTTSProvider(settings(doubao_tts_voice_id="another_voice"), storage=storage)
    minimax = MiniMaxTTSProvider(
        ProviderSettings(mode="live", minimax_api_key="k", minimax_tts_voice_id="v"), storage=storage
    )
    slower = SpeechProfile(speed=0.9)

    keys = {
        base.cache_key(TEXT, []),
        base.cache_key(TEXT, [], profile=slower),
        base.cache_key(TEXT + "。", []),
        base.cache_key(TEXT, ["pause_short"]),
        other_voice.cache_key(TEXT, []),
        minimax.cache_key(TEXT, []),
    }

    assert len(keys) == 6
    assert base.cache_key(TEXT, []).endswith(".wav") and minimax.cache_key(TEXT, []).endswith(".mp3")


def test_the_speed_multiplier_is_converted_to_doubaos_rate_scale() -> None:
    def rate(speed: float) -> int:
        return speech_rate_for(SpeechProfile(speed=speed))

    assert speech_rate_for(None) == 0
    assert (rate(1.0), rate(0.9), rate(1.02), rate(0.98)) == (0, -10, 2, -2)
    assert (rate(0.5), rate(2.0)) == (-50, 100)  # the ends of both scales
    assert DoubaoTTSProvider.speech_speed_baseline == 1.0


def test_the_request_carries_the_converted_rate_and_not_the_minimax_tags(tmp_path) -> None:  # type: ignore[no-untyped-def]
    rig = Rig(tmp_path, lambda _r: httpx.Response(200, content=stream(pcm(0.5))))

    run(rig, "你好 (breath)", cues=["breath"], profile=SpeechProfile(speed=0.95))

    sent = json.loads(rig.requests[0].content)["req_params"]
    assert sent["audio_params"]["speech_rate"] == -5
    assert sent["text"] == "你好"  # the cue marker is for MiniMax; this voice would read it out


def test_a_missing_receipt_is_unknown_and_a_reported_zero_stays_zero() -> None:
    assert price_for(None)["estimated_cost_cny"] is None
    assert price_for(None)["cost_basis"] == "usage_missing"
    assert price_for(0)["estimated_cost_cny"] == 0.0
    assert price_for(10_000)["estimated_cost_cny"] == pytest.approx(3.0)


def test_audio_that_is_empty_or_malformed_is_rejected_and_recorded(tmp_path) -> None:  # type: ignore[no-untyped-def]
    rig = Rig(tmp_path, lambda _r: httpx.Response(200, content=stream(b"\x01", text_words=3)))

    with pytest.raises(ProviderInvalidResponseError):
        run(rig)  # an odd number of PCM bytes cannot be 16-bit samples

    (event,) = rig.events()
    assert event.metadata["failed_stage"] == "validate"
    assert event.metadata["billed_characters"] == 3  # what the service said it billed is still kept


def test_doubao_needs_its_own_key_and_never_a_minimax_one(tmp_path) -> None:  # type: ignore[no-untyped-def]
    storage = LocalObjectStorageProvider(tmp_path / "audio")
    chosen = ProviderSettings(mode="live", tts_provider="doubao", doubao_tts_api_key="k")
    assert isinstance(build_tts_provider(chosen, storage, UsageLedger()), DoubaoTTSProvider)

    with pytest.raises(ProviderConfigurationError):
        build_tts_provider(
            ProviderSettings(mode="live", tts_provider="doubao", minimax_api_key="m", minimax_tts_voice_id="v"),
            storage,
            UsageLedger(),
        )
    # MiniMax remains available when it is asked for
    explicit = ProviderSettings(mode="live", tts_provider="minimax", minimax_api_key="m", minimax_tts_voice_id="v")
    assert isinstance(build_tts_provider(explicit, storage, UsageLedger()), MiniMaxTTSProvider)


def test_the_settings_read_the_selector_and_hide_the_key(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("WAVECAST_TTS_PROVIDER", "doubao")
    monkeypatch.setenv("DOUBAO_TTS_API_KEY", "k-very-secret")
    monkeypatch.setenv("DOUBAO_TTS_VOICE_ID", "voice-x")

    loaded = ProviderSettings.from_env()

    assert loaded.resolved_tts_provider == "doubao"
    assert loaded.doubao_tts_voice_id == "voice-x"
    assert "k-very-secret" not in repr(loaded)


def test_both_entry_points_build_it_with_the_ledger_each_one_reports_from() -> None:
    """Import the real API module and build the real assembly under a Doubao-only configuration."""

    code = (
        "import json, sys\n"
        f"sys.path[:0] = [{str(REPO / 'backend')!r}, {str(REPO)!r}]\n"
        "from services.api import main as api\n"
        "from wavecast.assembly import create_episode_assembly_service\n"
        "from wavecast.providers.config import ProviderSettings\n"
        "from wavecast.storage import LocalObjectStorageProvider\n"
        "import tempfile\n"
        "shared = api._usage_ledger()\n"
        "service = create_episode_assembly_service(ProviderSettings.from_env(), "
        "storage=LocalObjectStorageProvider(tempfile.mkdtemp()))\n"
        "print(json.dumps({'api': type(api._tts_provider).__name__, 'api_ledger': api._tts_provider.ledger is shared,"
        " 'assembly': type(service.materializer.tts_provider).__name__, 'assembly_ledger': service.materializer.tts_provider.ledger is service.ledger}))\n"
    )
    env = {
        "PATH": "/usr/bin:/bin",
        "WAVECAST_PROVIDER_MODE": "live",
        "WAVECAST_RECOMMENDATION_PLANNER": "deterministic",
        "WAVECAST_MUSIC_PROVIDER": "mock",
        "WAVECAST_TTS_PROVIDER": "doubao",
        "WAVECAST_PROPOSAL_PLANNER": "deepseek",
        "DOUBAO_TTS_API_KEY": "placeholder",  # and no MiniMax key at all
        "DEEPSEEK_API_KEY": "placeholder",
        "ARK_API_KEY": "placeholder",
        "EXA_API_KEY": "placeholder",
        "TAVILY_API_KEY": "placeholder",
    }
    done = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=180, check=False
    )

    assert done.returncode == 0, done.stderr[-800:]
    assert json.loads(done.stdout.strip().splitlines()[-1]) == {
        "api": "DoubaoTTSProvider",
        "api_ledger": True,
        "assembly": "DoubaoTTSProvider",
        "assembly_ledger": True,
    }


def test_the_opening_hosts_doubao_voice_reaches_the_episode_report(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Through the real API path: proposal -> episode -> opening host -> usage report."""

    from fastapi.testclient import TestClient

    from services.api import main as api_module

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=stream(pcm(2.0), text_words=52))

    chosen = settings()
    provider = api_module._build_tts_provider(  # noqa: SLF001
        chosen, LocalObjectStorageProvider(tmp_path / "audio"), api_module._usage_ledger()  # noqa: SLF001
    )
    assert isinstance(provider, DoubaoTTSProvider)
    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    materializer = api_module._build_narration_materializer(  # noqa: SLF001
        chosen, provider, provider.storage, api_module._usage_ledger()  # noqa: SLF001
    )
    monkeypatch.setattr(api_module, "narration_materializer", materializer)
    client = TestClient(api_module.app)
    owner = {"X-Wavecast-Listener": "doubao-tts-opening"}

    batch = client.post(
        "/api/program-proposals",
        json={"prompt": "doubao voice opens the programme", "count": 1, "duration_intent": "SHORT"},
        headers=owner,
    )
    created = client.post(f"/api/episodes/from-seed/{batch.json()['proposals'][0]['id']}", headers=owner)
    assert created.status_code == 200, created.text
    episode_id = created.json()["id"]
    asyncio.run(api_module._usage_ledger().flush())  # noqa: SLF001
    stored = asyncio.run(api_module._usage_event_store.load(episode_id))  # noqa: SLF001
    report = client.get(f"/api/episodes/{episode_id}/usage", headers=owner).json()

    assert len(requests) == 1
    (voice,) = [e for e in stored if e.provider == "doubao_tts"]
    assert voice.metadata["billed_characters"] == 52
    assert voice.metadata["estimated_cost_cny"] == pytest.approx(0.0156)
    assert report["costs"]["cny"]["priced_calls"] >= 1
    asyncio.run(provider.client.aclose())
