"""Which voices speak a researched passage, and with what: built from settings, off by default.

``None`` means the feature is off: no dialogue speech provider exists, so a dialogue segment
cannot be voiced and the programme stays on the one-voice path.  ``mock`` is the credential-free
silent audio used by tests and local runs.  ``doubao`` needs its credentials *and* a podcast
transport; none ships yet (see ``doubao_podcast``), so it is refused at startup instead of
failing on the first passage.
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
    missing = [
        name
        for name, value in (
            ("DOUBAO_APP_ID", settings.doubao_app_id),
            ("DOUBAO_ACCESS_TOKEN", settings.doubao_access_token),
            ("DOUBAO_RESOURCE_ID", settings.doubao_resource_id),
        )
        if not value
    ]
    if missing:
        raise ProviderConfigurationError("doubao dialogue speech requires " + ", ".join(missing))
    if transport is None:
        raise ProviderConfigurationError(
            "doubao dialogue speech has no podcast transport in this build; "
            "use WAVECAST_DIALOGUE_SPEECH_PROVIDER=mock until it is added"
        )
    return DialogueVoicing(
        speech=DoubaoPodcastSpeechProvider(transport, storage, ledger=ledger),
        voices=VOICE_COMBINATION_B,
        speed=float(SPEECH_RATE_B),
        audio_format=DEFAULT_AUDIO_FORMAT,
    )
