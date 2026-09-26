import asyncio

import httpx
import pytest
from wavecast.providers.config import ProviderSettings
from wavecast.providers.errors import (
    ProviderAuthenticationError,
    ProviderBudgetExceededError,
    ProviderConfigurationError,
    ProviderInvalidResponseError,
    ProviderRateLimitError,
    ProviderUnavailableError,
    is_retryable,
)
from wavecast.providers.http import request_json
from wavecast.providers.routing import SearchIntent, SearchRouter
from wavecast.providers.search import ExaSearchProvider, TavilySearchProvider
from wavecast.providers.usage import UsageEvent, UsageLedger


def test_mock_mode_is_credential_free(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "WAVECAST_PROVIDER_MODE",
        "DEEPSEEK_API_KEY",
        "EXA_API_KEY",
        "TAVILY_API_KEY",
        "AUDIUS_API_KEY",
        "AUDIUS_BEARER_TOKEN",
        "MINIMAX_API_KEY",
        "MINIMAX_TTS_VOICE_ID",
        "WAVECAST_PROPOSAL_PLANNER",
        "WAVECAST_MUSIC_PROVIDER",
        "WAVECAST_FAST_START_PROVIDER",
        "WAVECAST_RESEARCH_PROVIDER",
        "WAVECAST_CURATOR_PROVIDER",
        "WAVECAST_WRITER_PROVIDER",
        "WAVECAST_TTS_PROVIDER",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = ProviderSettings.from_env()

    assert settings.mode == "mock"
    assert settings.resolved_proposal_planner == "mock"
    assert settings.resolved_music_provider == "mock"
    assert settings.resolved_fast_start_provider == "mock"
    assert settings.resolved_research_provider == "mock"
    assert settings.resolved_curator_provider == "mock"
    assert settings.resolved_writer_provider == "mock"
    assert settings.resolved_tts_provider == "mock"
    assert settings.minimax_tts_model == "speech-2.8-turbo"
    assert settings.minimax_tts_speed == 0.8
    with pytest.raises(ProviderConfigurationError):
        settings.credential_for("deepseek")


def test_global_live_is_only_the_default_for_inherited_capabilities() -> None:
    settings = ProviderSettings(mode="live")

    assert settings.resolved_proposal_planner == "deepseek"
    assert settings.resolved_music_provider == "auto"
    assert settings.resolved_fast_start_provider == "deepseek"
    assert settings.resolved_research_provider == "live"
    assert settings.resolved_curator_provider == "deepseek"
    assert settings.resolved_writer_provider == "deepseek"
    assert settings.resolved_tts_provider == "minimax"
    assert settings.has_live_episode_capability
    assert settings.has_live_progressive_intelligence


def test_capability_overrides_can_enable_one_live_boundary_under_global_mock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WAVECAST_PROVIDER_MODE", "mock")
    monkeypatch.setenv("WAVECAST_PROPOSAL_PLANNER", "deepseek")
    monkeypatch.setenv("WAVECAST_MUSIC_PROVIDER", "netease")
    monkeypatch.setenv("WAVECAST_TTS_PROVIDER", "minimax")

    settings = ProviderSettings.from_env()

    assert settings.resolved_proposal_planner == "deepseek"
    assert settings.resolved_music_provider == "netease"
    assert settings.resolved_fast_start_provider == "mock"
    assert settings.resolved_research_provider == "mock"
    assert settings.resolved_curator_provider == "mock"
    assert settings.resolved_writer_provider == "mock"
    assert settings.resolved_tts_provider == "minimax"
    assert settings.has_live_episode_capability
    assert not settings.has_live_progressive_intelligence
    assert settings.for_live_capability().mode == "live"



def test_progressive_intelligence_flag_ignores_music_and_tts_only() -> None:
    passive = ProviderSettings(
        mode="mock",
        music_provider="netease",
        tts_provider="minimax",
    )
    active = ProviderSettings(
        mode="mock",
        fast_start_provider="deepseek",
    )

    assert not passive.has_live_progressive_intelligence
    assert active.has_live_progressive_intelligence

def test_invalid_capability_selector_fails_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WAVECAST_WRITER_PROVIDER", "anything")

    with pytest.raises(ProviderConfigurationError, match="WAVECAST_WRITER_PROVIDER"):
        ProviderSettings.from_env()


def test_minimax_tts_configuration_is_explicit_and_optional(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MINIMAX_TTS_BASE_URL", "https://minimax.test")
    monkeypatch.setenv("MINIMAX_TTS_MODEL", "speech-2.8-hd")
    monkeypatch.setenv("MINIMAX_TTS_VOICE_ID", "radio-voice")
    monkeypatch.setenv("MINIMAX_TTS_SPEED", "1.1")

    settings = ProviderSettings.from_env()

    assert settings.minimax_api_key is None
    assert settings.minimax_tts_base_url == "https://minimax.test"
    assert settings.minimax_tts_model == "speech-2.8-hd"
    assert settings.minimax_tts_voice_id == "radio-voice"
    assert settings.minimax_tts_speed == 1.1


def test_audius_api_key_and_bearer_token_are_separate_env_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUDIUS_API_KEY", "app-key")
    monkeypatch.setenv("AUDIUS_BEARER_TOKEN", "server-token")

    settings = ProviderSettings.from_env()

    assert settings.audius_api_key == "app-key"
    assert settings.audius_bearer_token == "server-token"


def test_music_sidecar_urls_are_optional_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NETEASE_MUSIC_API_BASE_URL", "http://netease-sidecar")
    monkeypatch.setenv("QQ_MUSIC_API_BASE_URL", "http://qq-sidecar")

    settings = ProviderSettings.from_env()

    assert settings.netease_music_api_base_url == "http://netease-sidecar"
    assert settings.qq_music_api_base_url == "http://qq-sidecar"


def test_deepseek_timeout_is_independent_from_search_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WAVECAST_PROVIDER_MODE", "live")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test")
    monkeypatch.setenv("EXA_API_KEY", "test")
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    monkeypatch.delenv("DEEPSEEK_TIMEOUT_SECONDS", raising=False)

    settings = ProviderSettings.from_env()

    assert settings.timeout_seconds == 20
    assert settings.deepseek_timeout_seconds == 20
    assert settings.deepseek_deep_timeout_seconds == 60
    assert settings.deepseek_max_output_tokens == 4096
    assert settings.deepseek_deep_max_output_tokens == 12288


def test_deep_timeout_can_be_configured_without_changing_hot_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WAVECAST_PROVIDER_MODE", "live")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test")
    monkeypatch.setenv("DEEPSEEK_DEEP_TIMEOUT_SECONDS", "47")
    monkeypatch.setenv("DEEPSEEK_DEEP_MAX_OUTPUT_TOKENS", "14000")

    settings = ProviderSettings.from_env()

    assert settings.deepseek_timeout_seconds == 20
    assert settings.deepseek_deep_timeout_seconds == 47
    assert settings.deepseek_deep_max_output_tokens == 14000


def test_search_providers_keep_the_shared_short_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    created_timeouts: list[float] = []

    class CapturingClient:
        def __init__(self, *, timeout: float) -> None:
            created_timeouts.append(timeout)

    monkeypatch.setattr("wavecast.providers.search.httpx.AsyncClient", CapturingClient)
    settings = ProviderSettings(
        mode="live",
        exa_api_key="test",
        tavily_api_key="test",
        timeout_seconds=17,
        deepseek_timeout_seconds=90,
    )

    ExaSearchProvider(settings)
    TavilySearchProvider(settings)

    assert created_timeouts == [17, 17]


def test_only_retryable_provider_errors_are_retried() -> None:
    assert is_retryable(ProviderRateLimitError("retry"))
    assert is_retryable(ProviderUnavailableError("retry"))
    assert not is_retryable(ProviderAuthenticationError("do not retry"))


def test_http_retry_is_bounded_and_does_not_retry_authentication() -> None:
    attempts = 0
    sleeps: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(429 if attempts == 1 else 200, json={"ok": True})

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    async def run() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        payload, _response = await request_json(
            client,
            provider="test",
            method="GET",
            url="https://example.test",
            max_attempts=2,
            sleep=sleep,
        )
        await client.aclose()
        assert payload == {"ok": True}

    asyncio.run(run())
    assert attempts == 2
    assert sleeps == [0.25]


def test_http_does_not_retry_authentication_errors() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(401, json={"error": "invalid key"})

    async def run() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with pytest.raises(ProviderAuthenticationError):
            await request_json(
                client,
                provider="test",
                method="GET",
                url="https://example.test",
                max_attempts=2,
            )
        await client.aclose()

    asyncio.run(run())
    assert attempts == 1


@pytest.mark.parametrize("status_code", [432, 433])
def test_tavily_usage_limits_are_budget_exceeded(status_code: int) -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(status_code, json={"detail": "usage limit reached"})

    async def run() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            with pytest.raises(ProviderBudgetExceededError):
                await request_json(
                    client,
                    provider="tavily",
                    method="POST",
                    url="https://example.test",
                    max_attempts=2,
                )
        finally:
            await client.aclose()

    asyncio.run(run())
    assert attempts == 1


def test_http_converts_malformed_json_to_a_provider_error() -> None:
    async def run() -> None:
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _request: httpx.Response(200, text="not json"))
        )
        with pytest.raises(ProviderInvalidResponseError):
            await request_json(
                client,
                provider="test",
                method="GET",
                url="https://example.test",
                max_attempts=1,
            )
        await client.aclose()

    asyncio.run(run())


def test_search_router_routes_explicit_intents_only() -> None:
    class Search:
        def __init__(self) -> None:
            self.queries: list[str] = []

        async def search(self, query: str, *, limit: int = 5) -> list[object]:
            del limit
            self.queries.append(query)
            return []

    async def run() -> None:
        discovery = Search()
        research = Search()
        router = SearchRouter(discovery=discovery, research=research)
        await router.search(SearchIntent.DISCOVERY, "discover")
        await router.search(SearchIntent.RESEARCH, "research")
        assert discovery.queries == ["discover"]
        assert research.queries == ["research"]
        with pytest.raises(ProviderUnavailableError):
            await router.search(SearchIntent.EXACT, "exact")

    asyncio.run(run())


def test_usage_ledger_aggregates_known_values_without_inventing_cost() -> None:
    ledger = UsageLedger()
    ledger.record(
        UsageEvent(
            provider="deepseek",
            operation="structured",
            elapsed_ms=12,
            input_tokens=11,
            output_tokens=7,
        )
    )
    ledger.record(
        UsageEvent(
            provider="exa",
            operation="search",
            elapsed_ms=20,
            actual_cost_usd=0.01,
            search_queries=1,
        )
    )
    ledger.record(
        UsageEvent(
            provider="tavily",
            operation="search",
            elapsed_ms=30,
            search_credits=2,
            search_queries=1,
        )
    )

    totals = ledger.totals()
    assert totals.input_tokens == 11
    assert totals.output_tokens == 7
    assert totals.search_queries == 2
    assert totals.search_credits == 2
    assert totals.actual_cost_usd == 0.01
    assert totals.estimated_cost_usd == 0


def test_usage_ledger_aggregates_by_stage() -> None:
    ledger = UsageLedger()
    ledger.record(
        UsageEvent(
            provider="deepseek",
            operation="structured",
            elapsed_ms=12,
            input_tokens=11,
            output_tokens=7,
            metadata={"stage": "fast_start"},
        )
    )
    ledger.record(
        UsageEvent(
            provider="tavily",
            operation="search",
            elapsed_ms=12,
            search_queries=1,
            search_credits=2,
            metadata={"stage": "background_research"},
        )
    )

    assert ledger.totals_for_stage("fast_start").output_tokens == 7
    assert ledger.totals_for_stage("background_research").search_credits == 2
