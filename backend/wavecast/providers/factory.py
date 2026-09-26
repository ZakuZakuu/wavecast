"""Provider-neutral construction of the configured music catalog registry."""

from __future__ import annotations

from .config import ProviderSettings
from .contracts import MusicProvider
from .errors import ProviderConfigurationError
from .fakes import MockMusicProvider
from .registry import MusicProviderRegistry


def build_music_registry(settings: ProviderSettings) -> MusicProviderRegistry:
    """Build the catalog registry shared by proposal and episode resolution."""

    selector = settings.resolved_music_provider
    if selector == "mock":
        provider = MockMusicProvider()
        return MusicProviderRegistry({"mock": provider}, preference=("mock",))

    live_settings = settings.for_live_capability()
    providers: dict[str, MusicProvider] = {}

    from .audius import AudiusMusicProvider
    from .netease import NeteaseMusicProvider
    from .qqmusic import QQMusicProvider

    if selector in {"auto", "netease"} and live_settings.netease_music_api_base_url:
        providers["netease"] = NeteaseMusicProvider(live_settings)
    if selector in {"auto", "qqmusic"} and live_settings.qq_music_api_base_url:
        providers["qqmusic"] = QQMusicProvider(live_settings)
    if selector in {"auto", "audius"} and (
        live_settings.audius_api_key or live_settings.audius_bearer_token
    ):
        providers["audius"] = AudiusMusicProvider(live_settings)

    if selector != "auto" and selector not in providers:
        raise ProviderConfigurationError(
            f"WAVECAST_MUSIC_PROVIDER={selector} is not configured"
        )
    if not providers:
        raise ProviderConfigurationError(
            "live music resolution requires at least one configured real music provider"
        )
    return MusicProviderRegistry(providers, preference=tuple(providers))
