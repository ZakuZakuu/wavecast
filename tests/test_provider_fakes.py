import asyncio

from wavecast.providers.fakes import FakeMusicProvider, FakeSearchProvider, FakeTTSProvider


def test_fake_providers_are_usable_without_credentials() -> None:
    search = asyncio.run(FakeSearchProvider().search("city pop"))
    tts = asyncio.run(FakeTTSProvider().synthesize("Hello, listener.", cues=["warm"]))
    track = asyncio.run(FakeMusicProvider().resolve_track("mock:opening"))

    assert search[0].provider == "fake-search"
    assert tts.asset_ref.startswith("fake-tts://")
    assert track.playable
