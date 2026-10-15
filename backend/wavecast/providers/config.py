"""Explicit, secret-safe provider configuration."""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from math import isfinite
from os import getenv
from typing import Literal, cast

from .errors import ProviderConfigurationError

ProviderMode = Literal["mock", "live"]
LLMCapabilitySelector = Literal["inherit", "mock", "deepseek", "ark"]
LLMChoice = Literal["mock", "deepseek", "ark"]
# Every text-model role.  Each can be bound to a model on its own; the pipeline never reaches
# for "the" LLM.  ``material`` (the shared story material) has no consumer yet.
LLMRole = Literal[
    "proposal",
    "fast_start",
    "research_plan",
    "material",
    "curator",
    "writer",
    "fact_check",
    "track_research",
]
LLM_ROLES: tuple[LLMRole, ...] = (
    "proposal",
    "fast_start",
    "research_plan",
    "material",
    "curator",
    "writer",
    "fact_check",
    "track_research",
)
ResearchCapabilitySelector = Literal["inherit", "mock", "live"]
MusicCapabilitySelector = Literal["inherit", "mock", "auto", "netease", "qqmusic", "audius"]
TTSCapabilitySelector = Literal["inherit", "mock", "minimax"]


@dataclass(frozen=True)
class ProviderSettings:
    mode: ProviderMode = "mock"
    deepseek_api_key: str | None = None
    exa_api_key: str | None = None
    tavily_api_key: str | None = None
    # Optional discovery signal (ranking/candidates only); absent = Last.fm is simply not used.
    lastfm_api_key: str | None = None
    minimax_api_key: str | None = None
    ark_api_key: str | None = field(default=None, repr=False)
    audius_api_key: str | None = None
    # Audius API keys identify the application and may be used in client-safe
    # requests. Bearer tokens authorize backend actions and must never reach
    # browser playback code.
    audius_bearer_token: str | None = None
    audius_base_url: str = "https://api.audius.co/v1"
    netease_music_api_base_url: str | None = None
    netease_music_api_bearer_token: str | None = field(default=None, repr=False)
    qq_music_api_base_url: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"
    ark_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    # Ark model id per role (ARK_<ROLE>_MODEL).  There is deliberately no default: model ids are
    # dated, and a role only needs one when it is bound to Ark.
    ark_models: Mapping[str, str] = field(default_factory=dict, hash=False)

    # Capability selectors default to "inherit": global mock keeps the capability
    # credential-free, while global live selects the established live provider.
    # Explicit overrides let production enable one boundary at a time.
    proposal_planner: LLMCapabilitySelector = "inherit"
    music_provider: MusicCapabilitySelector = "inherit"
    fast_start_provider: LLMCapabilitySelector = "inherit"
    research_provider: ResearchCapabilitySelector = "inherit"
    curator_provider: LLMCapabilitySelector = "inherit"
    writer_provider: LLMCapabilitySelector = "inherit"
    # Roles that used to share another role's model.  "inherit" keeps exactly that old sharing
    # (see ``resolved_llm``); an Ark Writer never drags these along.
    research_plan_provider: LLMCapabilitySelector = "inherit"
    material_provider: LLMCapabilitySelector = "inherit"
    fact_check_provider: LLMCapabilitySelector = "inherit"
    track_research_provider: LLMCapabilitySelector = "inherit"
    tts_provider: TTSCapabilitySelector = "inherit"
    # Researched two-host passages (ADR 0027).  Off by default: when off, nothing about
    # authoring or voicing changes.  "mock" voices a passage with credential-free silent audio
    # (tests and local runs); "doubao" needs the credentials below and a podcast transport.
    dialogue_radio: bool = False
    dialogue_speech_provider: Literal["mock", "doubao"] = "mock"
    # The podcast service takes its own API key (not an App ID / Access Token, and not the Ark
    # text key) and a resource id; the resource id below is the one the verified run used.
    doubao_podcast_api_key: str | None = field(default=None, repr=False)
    doubao_podcast_resource_id: str = "volc.service_type.10050"
    # ADR 0022: build a verified-playable catalog pool before the Curator chooses tracks.
    catalog_pool: bool = True
    # Size the route (tracks and chapters) from the requested duration instead of a fixed cap.
    duration_scaling: bool = True
    track_research: bool = True

    # Search remains deliberately short. Structured synthesis can be materially larger.
    timeout_seconds: float = 20.0
    deepseek_timeout_seconds: float = 20.0
    deepseek_deep_timeout_seconds: float = 60.0
    deepseek_max_output_tokens: int = 4096
    deepseek_deep_max_output_tokens: int = 12288
    # Ark answers measured proposal/writer calls in 22 to 55 s, hence the longer defaults.
    ark_timeout_seconds: float = 60.0
    ark_deep_timeout_seconds: float = 100.0
    ark_max_output_tokens: int = 4096
    ark_deep_max_output_tokens: int = 12288
    max_attempts: int = 2

    minimax_tts_base_url: str = "https://api.minimax.cn"
    minimax_tts_model: str = "speech-2.8-turbo"
    minimax_tts_voice_id: str | None = None
    minimax_tts_speed: float = 0.9
    # MiniMax "vol": 1 gives about -25 LUFS, quieter than the music it sits on; 1.7 gives about -20.
    minimax_tts_volume: float = 1.7
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
            lastfm_api_key=getenv("LASTFM_API_KEY") or None,
            minimax_api_key=getenv("MINIMAX_API_KEY"),
            ark_api_key=getenv("ARK_API_KEY") or None,
            audius_api_key=getenv("AUDIUS_API_KEY"),
            audius_bearer_token=getenv("AUDIUS_BEARER_TOKEN"),
            audius_base_url=getenv("AUDIUS_BASE_URL", "https://api.audius.co/v1"),
            netease_music_api_base_url=getenv("NETEASE_MUSIC_API_BASE_URL"),
            netease_music_api_bearer_token=getenv("NETEASE_MUSIC_API_BEARER_TOKEN"),
            qq_music_api_base_url=getenv("QQ_MUSIC_API_BASE_URL"),
            deepseek_base_url=getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            deepseek_model=getenv("DEEPSEEK_MODEL", "deepseek-flash"),
            ark_base_url=getenv("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
            ark_models={
                role: model
                for role in LLM_ROLES
                if (model := (getenv(f"ARK_{role.upper()}_MODEL") or "").strip())
            },
            proposal_planner=cast(
                LLMCapabilitySelector,
                _selector_from_env(
                    "WAVECAST_PROPOSAL_PLANNER",
                    _LLM_SELECTORS,
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
                    _LLM_SELECTORS,
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
                    _LLM_SELECTORS,
                ),
            ),
            writer_provider=cast(
                LLMCapabilitySelector,
                _selector_from_env(
                    "WAVECAST_WRITER_PROVIDER",
                    _LLM_SELECTORS,
                ),
            ),
            research_plan_provider=cast(
                LLMCapabilitySelector,
                _selector_from_env("WAVECAST_RESEARCH_PLAN_PROVIDER", _LLM_SELECTORS),
            ),
            material_provider=cast(
                LLMCapabilitySelector,
                _selector_from_env("WAVECAST_MATERIAL_PROVIDER", _LLM_SELECTORS),
            ),
            fact_check_provider=cast(
                LLMCapabilitySelector,
                _selector_from_env("WAVECAST_FACT_CHECK_PROVIDER", _LLM_SELECTORS),
            ),
            track_research_provider=cast(
                LLMCapabilitySelector,
                _selector_from_env("WAVECAST_TRACK_RESEARCH_PROVIDER", _LLM_SELECTORS),
            ),
            tts_provider=cast(
                TTSCapabilitySelector,
                _selector_from_env(
                    "WAVECAST_TTS_PROVIDER",
                    {"inherit", "mock", "minimax"},
                ),
            ),
            dialogue_radio=_flag_from_env("WAVECAST_DIALOGUE_RADIO", default="off"),
            dialogue_speech_provider=cast(
                Literal["mock", "doubao"],
                _selector_from_env(
                    "WAVECAST_DIALOGUE_SPEECH_PROVIDER", {"mock", "doubao"}, default="mock"
                ),
            ),
            doubao_podcast_api_key=getenv("DOUBAO_PODCAST_API_KEY") or None,
            doubao_podcast_resource_id=(
                getenv("DOUBAO_PODCAST_RESOURCE_ID") or "volc.service_type.10050"
            ),
            catalog_pool=_flag_from_env("WAVECAST_CATALOG_POOL", default="on"),
            duration_scaling=_flag_from_env("WAVECAST_DURATION_SCALING", default="on"),
            track_research=_flag_from_env("WAVECAST_TRACK_RESEARCH", default="on"),
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
            ark_timeout_seconds=_positive_float_from_env("ARK_TIMEOUT_SECONDS", default=60.0),
            ark_deep_timeout_seconds=_positive_float_from_env(
                "ARK_DEEP_TIMEOUT_SECONDS", default=100.0
            ),
            ark_max_output_tokens=_positive_int_from_env("ARK_MAX_OUTPUT_TOKENS", default=4096),
            ark_deep_max_output_tokens=_positive_int_from_env(
                "ARK_DEEP_MAX_OUTPUT_TOKENS", default=12288
            ),
            minimax_tts_base_url=getenv("MINIMAX_TTS_BASE_URL", "https://api.minimax.cn"),
            minimax_tts_model=getenv("MINIMAX_TTS_MODEL", "speech-2.8-turbo"),
            minimax_tts_voice_id=getenv("MINIMAX_TTS_VOICE_ID"),
            minimax_tts_speed=_positive_float_from_env("MINIMAX_TTS_SPEED", default=0.9),
            minimax_tts_volume=_positive_float_from_env("MINIMAX_TTS_VOLUME", default=1.7),
            minimax_tts_language_boost=getenv("MINIMAX_TTS_LANGUAGE_BOOST", "auto"),
        )

    @property
    def resolved_proposal_planner(self) -> LLMChoice:
        if self.proposal_planner == "inherit":
            return "mock" if self.mode == "mock" else "deepseek"
        return self.proposal_planner

    @property
    def resolved_music_provider(self) -> Literal["mock", "auto", "netease", "qqmusic", "audius"]:
        if self.music_provider == "inherit":
            return "mock" if self.mode == "mock" else "auto"
        return self.music_provider

    @property
    def resolved_fast_start_provider(self) -> LLMChoice:
        if self.fast_start_provider == "inherit":
            return "mock" if self.mode == "mock" else "deepseek"
        return self.fast_start_provider

    @property
    def resolved_research_provider(self) -> Literal["mock", "live"]:
        if self.research_provider == "inherit":
            return self.mode
        return self.research_provider

    @property
    def resolved_curator_provider(self) -> LLMChoice:
        if self.curator_provider == "inherit":
            return "mock" if self.mode == "mock" else "deepseek"
        return self.curator_provider

    @property
    def resolved_writer_provider(self) -> LLMChoice:
        if self.writer_provider == "inherit":
            return "mock" if self.mode == "mock" else "deepseek"
        return self.writer_provider

    @property
    def resolved_research_plan_provider(self) -> LLMChoice:
        if self.research_plan_provider == "inherit":
            # The planner used to share the research capability's model.
            return "mock" if self.resolved_research_provider == "mock" else "deepseek"
        return self.research_plan_provider

    @property
    def resolved_material_provider(self) -> LLMChoice:
        if self.material_provider == "inherit":
            return "mock" if self.mode == "mock" else "deepseek"
        return self.material_provider

    def _legacy_writer_choice(self) -> LLMChoice:
        """What the Writer's model was before roles were separate: the base configuration.

        An explicit ``mock`` or ``deepseek`` Writer keeps carrying the roles that used to share
        it; an Ark Writer does not, so switching the Writer cannot switch them too.
        """

        if self.writer_provider in ("mock", "deepseek"):
            return self.writer_provider
        return "mock" if self.mode == "mock" else "deepseek"

    @property
    def resolved_fact_check_provider(self) -> LLMChoice:
        if self.fact_check_provider == "inherit":
            return self._legacy_writer_choice()
        return self.fact_check_provider

    @property
    def resolved_track_research_provider(self) -> LLMChoice:
        if self.track_research_provider == "inherit":
            return self._legacy_writer_choice()
        return self.track_research_provider

    def resolved_llm(self, role: LLMRole) -> LLMChoice:
        return {
            "proposal": self.resolved_proposal_planner,
            "fast_start": self.resolved_fast_start_provider,
            "research_plan": self.resolved_research_plan_provider,
            "material": self.resolved_material_provider,
            "curator": self.resolved_curator_provider,
            "writer": self.resolved_writer_provider,
            "fact_check": self.resolved_fact_check_provider,
            "track_research": self.resolved_track_research_provider,
        }[role]

    def ark_model_for(self, role: LLMRole) -> str:
        model = self.ark_models.get(role)
        if not model:
            raise ProviderConfigurationError(
                f"the {role} role is bound to ark and requires ARK_{role.upper()}_MODEL"
            )
        return model

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

    @property
    def has_live_progressive_intelligence(self) -> bool:
        """Whether staged research/curation/writing should own episode generation."""
        return any(
            (
                self.resolved_fast_start_provider != "mock",
                self.resolved_research_provider != "mock",
                self.resolved_curator_provider != "mock",
                self.resolved_writer_provider != "mock",
            )
        )

    def for_live_capability(self) -> "ProviderSettings":
        """Allow one explicitly gated live adapter without flipping sibling capabilities."""
        return replace(self, mode="live")

    def credential_for(
        self, provider: Literal["deepseek", "exa", "tavily", "minimax", "ark"]
    ) -> str:
        if self.mode != "live":
            raise ProviderConfigurationError(
                f"{provider} live adapter requires live-capability settings"
            )
        key = {
            "deepseek": self.deepseek_api_key,
            "exa": self.exa_api_key,
            "tavily": self.tavily_api_key,
            "minimax": self.minimax_api_key,
            "ark": self.ark_api_key,
        }[provider]
        if not key:
            raise ProviderConfigurationError(f"{provider} requires its API key in live mode")
        return key


_LLM_SELECTORS = {"inherit", "mock", "deepseek", "ark"}


def _selector_from_env(name: str, allowed: set[str], default: str = "inherit") -> str:
    value = getenv(name, default).strip().lower()
    if value not in allowed:
        choices = ", ".join(sorted(allowed))
        raise ProviderConfigurationError(f"{name} must be one of: {choices}")
    return value


def _flag_from_env(name: str, default: str = "off") -> bool:
    value = getenv(name, default).strip().lower()
    if value in {"on", "true", "1"}:
        return True
    if value in {"off", "false", "0", ""}:
        return False
    raise ProviderConfigurationError(f"{name} must be on or off")


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
