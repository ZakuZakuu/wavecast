"""Small paid smoke checks. They are skipped unless pytest receives --run-live."""

import asyncio

import pytest
from pydantic import BaseModel
from wavecast.providers.config import ProviderSettings
from wavecast.providers.deepseek import DeepSeekLLMProvider
from wavecast.providers.search import ExaSearchProvider, TavilySearchProvider

pytestmark = pytest.mark.live


class TinyResponse(BaseModel):
    ok: bool


def _live_settings() -> ProviderSettings:
    settings = ProviderSettings.from_env()
    if settings.mode != "live":
        pytest.fail("set WAVECAST_PROVIDER_MODE=live before using --run-live")
    return settings


def test_live_deepseek_tiny_structured_response() -> None:
    async def run() -> None:
        provider = DeepSeekLLMProvider(_live_settings())
        result = await provider.structured('Return JSON {"ok": true}.', TinyResponse)
        assert result.ok is True
        await provider.client.close()

    asyncio.run(run())


def test_live_exa_small_search() -> None:
    async def run() -> None:
        provider = ExaSearchProvider(_live_settings())
        results = await provider.search("3rd Coast Jealousy music", limit=1)
        assert results
        await provider.aclose()

    asyncio.run(run())


def test_live_tavily_basic_small_search() -> None:
    async def run() -> None:
        provider = TavilySearchProvider(_live_settings())
        results = await provider.search("3rd Coast Jealousy DJMAX", limit=1)
        assert results
        await provider.aclose()

    asyncio.run(run())
