"""Optional QQ Music sidecar adapter."""

from __future__ import annotations

from .config import ProviderSettings
from .music_http import SidecarMusicProvider


class QQMusicProvider(SidecarMusicProvider):
    provider_name = "qqmusic"
    track_ref_prefix = "qqmusic"

    def _base_url_from_settings(self, settings: ProviderSettings) -> str | None:
        return settings.qq_music_api_base_url
