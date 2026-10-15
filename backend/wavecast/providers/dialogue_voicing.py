"""Which voices speak a researched passage, and with what: built from settings, off by default.

``None`` means the feature is off: no dialogue speech provider exists, so a dialogue segment
cannot be voiced and the programme stays on the one-voice path.  ``mock`` is the credential-free
silent audio used by tests and local runs.  ``doubao`` needs ``DOUBAO_PODCAST_API_KEY`` and is
refused at startup without it, instead of failing on the first passage.
"""

from __future__ import annotations

from dataclasses import dataclass

from wavecast.models.dialogue import VoiceRoleSnapshot
from wavecast.providers.config import ProviderSettings
from wavecast.providers.contracts import ObjectStorageProvider
from wavecast.providers.dialogue_speech import DialogueSpeechProvider, MockDialogueSpeechProvider
from wavecast.providers.doubao_podcast import (
    DEFAULT_AUDIO_FORMAT,
    DoubaoPodcastSpeechProvider,
    DoubaoPodcastWebSocketTransport,
    PodcastTransport,
)
from wavecast.providers.doubao_voices import SPEECH_RATE_B, VOICE_COMBINATION_B
from wavecast.providers.errors import ProviderConfigurationError
from wavecast.providers.usage import UsageLedger


@dataclass(frozen=True)
class DialogueVoicing:
    speech: DialogueSpeechProvider
    voices: tuple[VoiceRoleSnapshot, ...]
    speed: float | None
    audio_format: str | None


def build_dialogue_voicing(
    settings: ProviderSettings,
    storage: ObjectStorageProvider,
    *,
    ledger: UsageLedger | None = None,
    transport: PodcastTransport | None = None,
) -> DialogueVoicing | None:
    if not settings.dialogue_radio:
        return None
    if settings.dialogue_speech_provider == "mock":
        return DialogueVoicing(
            speech=MockDialogueSpeechProvider(storage),
            voices=VOICE_COMBINATION_B,
            speed=float(SPEECH_RATE_B),
            audio_format=None,
        )
    if not settings.doubao_podcast_api_key:
        raise ProviderConfigurationError("doubao dialogue speech requires DOUBAO_PODCAST_API_KEY")
    return DialogueVoicing(
        speech=DoubaoPodcastSpeechProvider(
            transport
            or DoubaoPodcastWebSocketTransport(
                settings.doubao_podcast_api_key, settings.doubao_podcast_resource_id
            ),
            storage,
            ledger=ledger,
        ),
        voices=VOICE_COMBINATION_B,
        speed=float(SPEECH_RATE_B),
        audio_format=DEFAULT_AUDIO_FORMAT,
    )
