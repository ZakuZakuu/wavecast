from wavecast.providers.config import ProviderSettings
from wavecast.providers.minimax import MiniMaxTTSProvider
from wavecast.speech import SpeechProfile
from wavecast.storage import LocalObjectStorageProvider


def test_minimax_maps_speech_profile_speed_and_language(tmp_path) -> None:
    settings = ProviderSettings(
        mode="live",
        minimax_api_key="test-key",
        minimax_tts_voice_id="test-voice",
        minimax_tts_language_boost="Chinese,English",
    )
    provider = MiniMaxTTSProvider(settings, storage=LocalObjectStorageProvider(tmp_path / "audio"))

    fallback = provider._request_payload("hello", "test-voice", SpeechProfile(speed=0.87))
    override = provider._request_payload(
        "hello",
        "test-voice",
        SpeechProfile(speed=0.88, language_boost="English"),
    )

    assert fallback["voice_setting"]["speed"] == 0.87
    assert fallback["language_boost"] == "Chinese,English"
    assert override["voice_setting"]["speed"] == 0.88
    assert override["language_boost"] == "English"
