import asyncio

from wavecast.providers.contracts import AudioAsset, AudioAssetType
from wavecast.providers.fakes import FakeTTSProvider


def test_audio_asset_has_provider_neutral_playback_contract() -> None:
    asset = AudioAsset(
        asset_id="audius:track-1",
        asset_type=AudioAssetType.MUSIC,
        provider="audius",
        playback_url="https://api.example.test/stream/track-1",
        duration=184,
        metadata={"title": "Track", "artist": "Artist"},
    )

    assert asset.model_dump()["asset_type"] == "MUSIC"
    assert asset.playback_url.endswith("track-1")
    assert asset.duration_seconds == 184
    assert asset.asset_ref == "audius:track-1"


def test_fake_tts_uses_the_same_audio_asset_contract() -> None:
    asset = asyncio.run(FakeTTSProvider().synthesize("Hello", cues=["warm"]))

    assert asset.asset_type is AudioAssetType.NARRATION
    assert asset.provider == "fake-tts"
    assert asset.playback_url.startswith("fake-tts://")
    assert asset.duration > 0
