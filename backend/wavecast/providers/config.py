"""Explicit, secret-safe provider configuration."""

from dataclasses import dataclass
from os import getenv
from typing import Literal, cast

from .errors import ProviderConfigurationError

ProviderMode = Literal["mock", "live"]


@dataclass(frozen=True)
class ProviderSettings:
    mode: ProviderMode = "mock"
    deepseek_api_key: str | None = None
    exa_api_key: str | None = None
    tavily_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"
    timeout_seconds: float = 20.0
    max_attempts: int = 2

    @classmethod
    def from_env(cls) -> "ProviderSettings":
        configured_mode = getenv("WAVECAST_PROVIDER_MODE", "mock").lower()
        if configured_mode not in {"mock", "live"}:
            raise ProviderConfigurationError("WAVECAST_PROVIDER_MODE must be mock or live")
        return cls(
            mode=cast(ProviderMode, configured_mode),
            deepseek_api_key=getenv("DEEPSEEK_API_KEY"),
            exa_api_key=getenv("EXA_API_KEY"),
            tavily_api_key=getenv("TAVILY_API_KEY"),
            deepseek_base_url=getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            deepseek_model=getenv("DEEPSEEK_MODEL", "deepseek-flash"),
        )

    def credential_for(self, provider: Literal["deepseek", "exa", "tavily"]) -> str:
        if self.mode != "live":
            raise ProviderConfigurationError(
                f"{provider} live adapter requires WAVECAST_PROVIDER_MODE=live"
            )
        key = {
            "deepseek": self.deepseek_api_key,
            "exa": self.exa_api_key,
            "tavily": self.tavily_api_key,
        }[provider]
        if not key:
            raise ProviderConfigurationError(f"{provider} requires its API key in live mode")
        return key
