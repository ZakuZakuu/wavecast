import asyncio

from wavecast.providers.fakes import (
    FakeMusicProvider,
    FakeSearchProvider,
    FakeTTSProvider,
    MockAudioProvider,
)


def test_fake_providers_are_usable_without_credentials() -> None:
    search = asyncio.run(FakeSearchProvider().search("city pop"))
    tts = asyncio.run(FakeTTSProvider().synthesize("Hello, listener.", cues=["warm"]))
    track = asyncio.run(FakeMusicProvider().resolve_track("mock:opening"))

    assert search[0].provider == "fake-search"
    assert tts.asset_ref.startswith("fake-tts://")
    assert track.playable


def test_mock_audio_provider_returns_browser_sources_without_network() -> None:
    provider = MockAudioProvider()

    music = provider.music_source("mock:opening")
    narration = provider.narration_source("segment-narration-1", "A transition", 10)

    assert music.source_url.startswith("/api/audio/mock/music/")
    assert music.duration_seconds == 22
    assert narration.source_url.startswith("/api/audio/mock/narration/")
    assert narration.duration_seconds == 10
