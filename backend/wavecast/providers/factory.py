"""Provider-neutral construction of the configured music catalog registry."""

from __future__ import annotations

from .config import ProviderSettings
from .contracts import MusicProvider
from .errors import ProviderConfigurationError
from .fakes import MockMusicProvider
from .registry import MusicProviderRegistry


def build_music_registry(settings: ProviderSettings) -> MusicProviderRegistry:
    """Build the catalog registry shared by proposal and episode resolution."""

    if settings.mode == "mock":
        provider = MockMusicProvider()
        return MusicProviderRegistry({"mock": provider}, preference=("mock",))

    providers: dict[str, MusicProvider] = {}

    from .audius import AudiusMusicProvider
    from .netease import NeteaseMusicProvider
    from .qqmusic import QQMusicProvider

    if settings.netease_music_api_base_url:
        providers["netease"] = NeteaseMusicProvider(settings)
    if settings.qq_music_api_base_url:
        providers["qqmusic"] = QQMusicProvider(settings)
    if settings.audius_api_key or settings.audius_bearer_token:
        providers["audius"] = AudiusMusicProvider(settings)
    if not providers:
        raise ProviderConfigurationError(
            "live music resolution requires at least one configured real music provider"
        )
    return MusicProviderRegistry(providers)
