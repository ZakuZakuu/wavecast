"""The single-voice TTS provider chosen by ``WAVECAST_TTS_PROVIDER``, for every place that needs one.

The API (the opening host) and the progressive assembly (bridges and outro) each build their own
provider so each records into the ledger it is given; this is the one place that decides which
vendor that is.  ``minimax`` stays the compatible default; ``doubao`` needs ``DOUBAO_TTS_API_KEY``
and never asks for a MiniMax key.
"""

from __future__ import annotations

from wavecast.providers.config import ProviderSettings
from wavecast.providers.contracts import ObjectStorageProvider, TTSProvider
from wavecast.providers.doubao_tts import DoubaoTTSProvider
from wavecast.providers.errors import ProviderConfigurationError
from wavecast.providers.fakes import MockTTSProvider
from wavecast.providers.minimax import MiniMaxTTSProvider
from wavecast.providers.usage import UsageLedger


def build_tts_provider(
    settings: ProviderSettings, storage: ObjectStorageProvider, ledger: UsageLedger
) -> TTSProvider:
    choice = settings.resolved_tts_provider
    if choice == "mock":
        return MockTTSProvider(storage)
    live_settings = settings.for_live_capability()
    if choice == "doubao":
        live_settings.credential_for("doubao_tts")
        if not live_settings.doubao_tts_voice_id:
            raise ProviderConfigurationError("doubao TTS requires DOUBAO_TTS_VOICE_ID")
        return DoubaoTTSProvider(live_settings, storage=storage, ledger=ledger)
    live_settings.credential_for("minimax")
    if not live_settings.minimax_tts_voice_id:
        raise ProviderConfigurationError("minimax TTS requires MINIMAX_TTS_VOICE_ID")
    return MiniMaxTTSProvider(live_settings, storage=storage, ledger=ledger)
