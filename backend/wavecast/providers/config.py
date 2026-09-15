"""Explicit, secret-safe provider configuration."""

from dataclasses import dataclass
from math import isfinite
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
    audius_api_key: str | None = None
    audius_base_url: str = "https://api.audius.co/v1"
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"
    # Search remains deliberately short. Structured synthesis can be materially larger.
    timeout_seconds: float = 20.0
    deepseek_timeout_seconds: float = 20.0
    deepseek_deep_timeout_seconds: float = 45.0
    deepseek_max_output_tokens: int = 4096
    deepseek_deep_max_output_tokens: int = 12288
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
            audius_api_key=getenv("AUDIUS_API_KEY"),
            audius_base_url=getenv("AUDIUS_BASE_URL", "https://api.audius.co/v1"),
            deepseek_base_url=getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            deepseek_model=getenv("DEEPSEEK_MODEL", "deepseek-flash"),
            deepseek_timeout_seconds=_positive_float_from_env(
                "DEEPSEEK_TIMEOUT_SECONDS", default=20.0
            ),
            deepseek_deep_timeout_seconds=_positive_float_from_env(
                "DEEPSEEK_DEEP_TIMEOUT_SECONDS", default=45.0
            ),
            deepseek_max_output_tokens=_positive_int_from_env(
                "DEEPSEEK_MAX_OUTPUT_TOKENS", default=4096
            ),
            deepseek_deep_max_output_tokens=_positive_int_from_env(
                "DEEPSEEK_DEEP_MAX_OUTPUT_TOKENS", default=12288
            ),
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


def _positive_float_from_env(name: str, *, default: float) -> float:
    value = getenv(name)
    if value is None:
        return default
    try:
        configured = float(value)
    except ValueError as error:
        raise ProviderConfigurationError(f"{name} must be a positive number") from error
    if not isfinite(configured) or configured <= 0:
        raise ProviderConfigurationError(f"{name} must be a positive number")
    return configured


def _positive_int_from_env(name: str, *, default: int) -> int:
    value = getenv(name)
    if value is None:
        return default
    try:
        configured = int(value)
    except ValueError as error:
        raise ProviderConfigurationError(f"{name} must be a positive integer") from error
    if configured <= 0:
        raise ProviderConfigurationError(f"{name} must be a positive integer")
    return configured
