"""Explicit, secret-safe provider configuration."""

from dataclasses import dataclass, replace
from math import isfinite
from os import getenv
from typing import Literal, cast

from .errors import ProviderConfigurationError

ProviderMode = Literal["mock", "live"]
LLMCapabilitySelector = Literal["inherit", "mock", "deepseek"]
ResearchCapabilitySelector = Literal["inherit", "mock", "live"]
MusicCapabilitySelector = Literal["inherit", "mock", "auto", "netease", "qqmusic", "audius"]
TTSCapabilitySelector = Literal["inherit", "mock", "minimax"]


@dataclass(frozen=True)
class ProviderSettings:
    mode: ProviderMode = "mock"
    deepseek_api_key: str | None = None
    exa_api_key: str | None = None
    tavily_api_key: str | None = None
    minimax_api_key: str | None = None
    audius_api_key: str | None = None
    # Audius API keys identify the application and may be used in client-safe
    # requests. Bearer tokens authorize backend actions and must never reach
    # browser playback code.
    audius_bearer_token: str | None = None
    audius_base_url: str = "https://api.audius.co/v1"
    netease_music_api_base_url: str | None = None
    qq_music_api_base_url: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"

    # Capability selectors default to "inherit": global mock keeps the capability
    # credential-free, while global live selects the established live provider.
    # Explicit overrides let production enable one boundary at a time.
    proposal_planner: LLMCapabilitySelector = "inherit"
    music_provider: MusicCapabilitySelector = "inherit"
    fast_start_provider: LLMCapabilitySelector = "inherit"
    research_provider: ResearchCapabilitySelector = "inherit"
    curator_provider: LLMCapabilitySelector = "inherit"
    writer_provider: LLMCapabilitySelector = "inherit"
    tts_provider: TTSCapabilitySelector = "inherit"

    # Search remains deliberately short. Structured synthesis can be materially larger.
    timeout_seconds: float = 20.0
    deepseek_timeout_seconds: float = 20.0
    deepseek_deep_timeout_seconds: float = 60.0
    deepseek_max_output_tokens: int = 4096
    deepseek_deep_max_output_tokens: int = 12288
    max_attempts: int = 2

    minimax_tts_base_url: str = "https://api.minimax.io"
    minimax_tts_model: str = "speech-2.8-turbo"
    minimax_tts_voice_id: str | None = None
    minimax_tts_speed: float = 0.8
    minimax_tts_language_boost: str = "auto"

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
            minimax_api_key=getenv("MINIMAX_API_KEY"),
            audius_api_key=getenv("AUDIUS_API_KEY"),
            audius_bearer_token=getenv("AUDIUS_BEARER_TOKEN"),
            audius_base_url=getenv("AUDIUS_BASE_URL", "https://api.audius.co/v1"),
            netease_music_api_base_url=getenv("NETEASE_MUSIC_API_BASE_URL"),
            qq_music_api_base_url=getenv("QQ_MUSIC_API_BASE_URL"),
            deepseek_base_url=getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            deepseek_model=getenv("DEEPSEEK_MODEL", "deepseek-flash"),
            proposal_planner=cast(
                LLMCapabilitySelector,
                _selector_from_env(
                    "WAVECAST_PROPOSAL_PLANNER",
                    {"inherit", "mock", "deepseek"},
                ),
            ),
            music_provider=cast(
                MusicCapabilitySelector,
                _selector_from_env(
                    "WAVECAST_MUSIC_PROVIDER",
                    {"inherit", "mock", "auto", "netease", "qqmusic", "audius"},
                ),
            ),
            fast_start_provider=cast(
                LLMCapabilitySelector,
                _selector_from_env(
                    "WAVECAST_FAST_START_PROVIDER",
                    {"inherit", "mock", "deepseek"},
                ),
            ),
            research_provider=cast(
                ResearchCapabilitySelector,
                _selector_from_env(
                    "WAVECAST_RESEARCH_PROVIDER",
                    {"inherit", "mock", "live"},
                ),
            ),
            curator_provider=cast(
                LLMCapabilitySelector,
                _selector_from_env(
                    "WAVECAST_CURATOR_PROVIDER",
                    {"inherit", "mock", "deepseek"},
                ),
            ),
            writer_provider=cast(
                LLMCapabilitySelector,
                _selector_from_env(
                    "WAVECAST_WRITER_PROVIDER",
                    {"inherit", "mock", "deepseek"},
                ),
            ),
            tts_provider=cast(
                TTSCapabilitySelector,
                _selector_from_env(
                    "WAVECAST_TTS_PROVIDER",
                    {"inherit", "mock", "minimax"},
                ),
            ),
            deepseek_timeout_seconds=_positive_float_from_env(
                "DEEPSEEK_TIMEOUT_SECONDS", default=20.0
            ),
            deepseek_deep_timeout_seconds=_positive_float_from_env(
                "DEEPSEEK_DEEP_TIMEOUT_SECONDS", default=60.0
            ),
            deepseek_max_output_tokens=_positive_int_from_env(
                "DEEPSEEK_MAX_OUTPUT_TOKENS", default=4096
            ),
            deepseek_deep_max_output_tokens=_positive_int_from_env(
                "DEEPSEEK_DEEP_MAX_OUTPUT_TOKENS", default=12288
            ),
            minimax_tts_base_url=getenv("MINIMAX_TTS_BASE_URL", "https://api.minimax.io"),
            minimax_tts_model=getenv("MINIMAX_TTS_MODEL", "speech-2.8-turbo"),
            minimax_tts_voice_id=getenv("MINIMAX_TTS_VOICE_ID"),
            minimax_tts_speed=_positive_float_from_env("MINIMAX_TTS_SPEED", default=0.8),
            minimax_tts_language_boost=getenv("MINIMAX_TTS_LANGUAGE_BOOST", "auto"),
        )

    @property
    def resolved_proposal_planner(self) -> Literal["mock", "deepseek"]:
        if self.proposal_planner == "inherit":
            return "mock" if self.mode == "mock" else "deepseek"
        return self.proposal_planner

    @property
    def resolved_music_provider(self) -> Literal["mock", "auto", "netease", "qqmusic", "audius"]:
        if self.music_provider == "inherit":
            return "mock" if self.mode == "mock" else "auto"
        return self.music_provider

    @property
    def resolved_fast_start_provider(self) -> Literal["mock", "deepseek"]:
        if self.fast_start_provider == "inherit":
            return "mock" if self.mode == "mock" else "deepseek"
        return self.fast_start_provider

    @property
    def resolved_research_provider(self) -> Literal["mock", "live"]:
        if self.research_provider == "inherit":
            return self.mode
        return self.research_provider

    @property
    def resolved_curator_provider(self) -> Literal["mock", "deepseek"]:
        if self.curator_provider == "inherit":
            return "mock" if self.mode == "mock" else "deepseek"
        return self.curator_provider

    @property
    def resolved_writer_provider(self) -> Literal["mock", "deepseek"]:
        if self.writer_provider == "inherit":
            return "mock" if self.mode == "mock" else "deepseek"
        return self.writer_provider

    @property
    def resolved_tts_provider(self) -> Literal["mock", "minimax"]:
        if self.tts_provider == "inherit":
            return "mock" if self.mode == "mock" else "minimax"
        return self.tts_provider

    @property
    def has_live_episode_capability(self) -> bool:
        return any(
            (
                self.resolved_music_provider != "mock",
                self.resolved_fast_start_provider != "mock",
                self.resolved_research_provider != "mock",
                self.resolved_curator_provider != "mock",
                self.resolved_writer_provider != "mock",
                self.resolved_tts_provider != "mock",
            )
        )

    def for_live_capability(self) -> "ProviderSettings":
        """Allow one explicitly gated live adapter without flipping sibling capabilities."""
        return replace(self, mode="live")

    def credential_for(self, provider: Literal["deepseek", "exa", "tavily", "minimax"]) -> str:
        if self.mode != "live":
            raise ProviderConfigurationError(
                f"{provider} live adapter requires live-capability settings"
            )
        key = {
            "deepseek": self.deepseek_api_key,
            "exa": self.exa_api_key,
            "tavily": self.tavily_api_key,
            "minimax": self.minimax_api_key,
        }[provider]
        if not key:
            raise ProviderConfigurationError(f"{provider} requires its API key in live mode")
        return key


def _selector_from_env(name: str, allowed: set[str]) -> str:
    value = getenv(name, "inherit").strip().lower()
    if value not in allowed:
        choices = ", ".join(sorted(allowed))
        raise ProviderConfigurationError(f"{name} must be one of: {choices}")
    return value


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
