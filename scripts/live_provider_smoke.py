"""Explicitly opt-in smoke command for the three live Phase 2 provider adapters."""

import argparse
import asyncio
import json
from typing import Literal

from pydantic import BaseModel
from wavecast.providers.config import ProviderSettings
from wavecast.providers.deepseek import DeepSeekLLMProvider
from wavecast.providers.errors import ProviderConfigurationError, ProviderError
from wavecast.providers.search import ExaSearchProvider, TavilySearchProvider
from wavecast.providers.usage import UsageLedger


class SmokeResponse(BaseModel):
    status: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=["all", "deepseek", "exa", "tavily"], default="all")
    return parser.parse_args()


def require_live_settings() -> ProviderSettings:
    settings = ProviderSettings.from_env()
    if settings.mode != "live":
        raise ProviderConfigurationError("set WAVECAST_PROVIDER_MODE=live for a paid smoke call")
    return settings


async def run(selected: Literal["all", "deepseek", "exa", "tavily"]) -> None:
    settings = require_live_settings()
    ledger = UsageLedger()
    if selected in {"all", "deepseek"}:
        provider = DeepSeekLLMProvider(settings, ledger=ledger)
        result = await provider.structured('Return JSON {"status":"ok"}.', SmokeResponse)
        print(f"DeepSeek OK: {result.model_dump_json()}")
        await provider.client.close()
    if selected in {"all", "exa"}:
        provider = ExaSearchProvider(settings, ledger=ledger)
        results = await provider.search("3rd Coast Jealousy music", limit=1)
        print(f"Exa OK: {json.dumps([item.model_dump() for item in results], ensure_ascii=False)}")
        await provider.aclose()
    if selected in {"all", "tavily"}:
        provider = TavilySearchProvider(settings, ledger=ledger)
        results = await provider.search("3rd Coast Jealousy DJMAX", limit=1)
        print(
            f"Tavily OK: {json.dumps([item.model_dump() for item in results], ensure_ascii=False)}"
        )
        await provider.aclose()
    print(f"Usage: {ledger.totals().model_dump_json()}")


if __name__ == "__main__":
    arguments = parse_args()
    try:
        asyncio.run(run(arguments.provider))
    except ProviderError as error:
        raise SystemExit(f"Live provider smoke failed: {error}") from error
