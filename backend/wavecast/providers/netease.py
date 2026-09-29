"""Optional NetEase Cloud Music sidecar adapter."""

from __future__ import annotations

from .config import ProviderSettings
from .music_http import SidecarMusicProvider


class NeteaseMusicProvider(SidecarMusicProvider):
    provider_name = "netease"
    track_ref_prefix = "netease"
    timing_profile_path_enabled = True

    def _base_url_from_settings(self, settings: ProviderSettings) -> str | None:
        return settings.netease_music_api_base_url
